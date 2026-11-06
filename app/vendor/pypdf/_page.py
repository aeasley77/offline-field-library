Warning: truncated output (original token count: 26310)
Total output lines: 2695

# Copyright (c) 2006, Mathieu Fenniak
# Copyright (c) 2007, Ashish Kulkarni <kulkarni.ashish@gmail.com>
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
# * The name of the author may not be used to endorse or promote products
# derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import math
from collections.abc import Iterable, Iterator, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import (
    Any,
    Callable,
    Literal,
    Optional,
    Union,
    cast,
    overload,
)

from ._configuration import get_configuration
from ._protocols import PdfCommonDocProtocol
from ._text_extraction import (
    _layout_mode,
)
from ._text_extraction._text_extractor import TextExtraction
from ._utils import (
    CompressedTransformationMatrix,
    TransformationMatrixType,
    _human_readable_bytes,
    _TraversalState,
    deprecate,
    deprecate_no_replacement,
    deprecate_with_replacement,
    logger_warning,
    matrix_multiply,
)
from .actions import Action, PageTrigger
from .constants import (
    _INLINE_IMAGE_KEY_MAPPING,
    _INLINE_IMAGE_VALUE_MAPPING,
    AnnotationDictionaryAttributes,
    ImageAttributes,
)
from .constants import PageAttributes as PG
from .constants import Resources as RES
from .errors import PageSizeNotDefinedError, PdfReadError
from .generic import (
    ArrayObject,
    ContentStream,
    DictionaryObject,
    EncodedStreamObject,
    FloatObject,
    IndirectObject,
    NameObject,
    NullObject,
    NumberObject,
    PdfObject,
    RectangleObject,
    StreamObject,
    is_null_or_none,
)
from .generic._font import Font

try:
    from PIL.Image import Image

    pil_not_imported = False
except ImportError:
    Image = object  # type: ignore[assignment,misc,unused-ignore]  # TODO: Remove unused-ignore on Python 3.10
    pil_not_imported = True  # error will be raised only when using images

MERGE_CROP_BOX = "cropbox"  # DEPRECATED: Use pypdf.Configuration.


def _get_page_resources(obj: Any) -> DictionaryObject:
    """Return the inherited /Resources, or an empty dictionary if malformed."""
    resources = obj.get_inherited(key=PG.RESOURCES, default=DictionaryObject())
    if is_null_or_none(resources):
        return DictionaryObject()
    if not isinstance(resources, DictionaryObject):
        logger_warning(
            "Page resources are not a dictionary: %(resources)s",
            source=__name__,
            resources=resources,
        )
        return DictionaryObject()
    return resources


def _get_font_resources(resources: Any) -> DictionaryObject:
    """Return the /Font resources, or an empty dictionary if missing or malformed."""
    fonts = resources.get(RES.FONT)
    if is_null_or_none(fonts):
        return DictionaryObject()
    fonts = fonts.get_object()
    if not isinstance(fonts, DictionaryObject):
        logger_warning(
            "Font resources are not a dictionary: %(fonts)s",
            source=__name__,
            fonts=fonts,
        )
        return DictionaryObject()
    return fonts


def _get_rectangle(self: Any, name: str, defaults: Iterable[str]) -> RectangleObject:
    retval: Optional[PdfObject] = self.get(name)
    if isinstance(retval, RectangleObject):
        return retval
    if is_null_or_none(retval):
        for d in defaults:
            retval = self.get(d)
            if retval is not None:
                break
    if isinstance(retval, IndirectObject):
        # Pages of a writer have no `pdf`, the reference knows its own document.
        retval = retval.get_object()
    if not isinstance(retval, ArrayObject):
        raise ValueError(f"Expected an array of four values for {name}, got {retval}")
    if (length := len(retval)) != 4:
        if length > 4:
            # Keep backwards-compatibility with files previously written in a
            # broken way by pypdf, which carried more than four values.
            logger_warning(
                "Expected four values, got %(length)d: %(retval)s",
                source=__name__,
                length=length,
                retval=retval,
            )
            retval = RectangleObject(tuple(retval[:4]))
        else:
            raise ValueError(
                f"Expected four values for {name}, got {length}: {retval}"
            )
    else:
        retval = RectangleObject(retval)
    _set_rectangle(self, name, retval)
    return retval


def _set_rectangle(self: Any, name: str, value: Union[RectangleObject, float]) -> None:
    if isinstance(value, (list, tuple)) and len(value) < 4:
        # The getter tolerates more than four values for backwards compatibility
        # but cannot do anything with fewer, so writing them would produce a page
        # whose box cannot be read back.
        raise ValueError(
            f"Expected four values for {name}, got {len(value)}: {value}"
        )
    self[NameObject(name)] = value


def _delete_rectangle(self: Any, name: str) -> None:
    del self[name]


def _create_rectangle_accessor(name: str, fallback: Iterable[str]) -> property:
    return property(
        lambda self: _get_rectangle(self, name, fallback),
        lambda self, value: _set_rectangle(self, name, value),
        lambda self: _delete_rectangle(self, name),
    )


class Transformation:
    """
    Represent a 2D transformation.

    The transformation between two coordinate systems is represented by a 3-by-3
    transformation matrix with the following form::

        a b 0
        c d 0
        e f 1

    Because a transformation matrix has only six elements that can be changed,
    it is usually specified in PDF as the six-element array [ a b c d e f ].

    Coordinate transformations are expressed as matrix multiplications::

                                 a b 0
     [ x′ y′ 1 ] = [ x y 1 ] ×   c d 0
                                 e f 1


    Example:
        >>> from pypdf import PdfWriter, Transformation
        >>> page = PdfWriter().add_blank_page(800, 600)
        >>> op = Transformation().scale(sx=2, sy=3).translate(tx=10, ty=20)
        >>> page.add_transformation(op)

    """

    def __init__(self, ctm: CompressedTransformationMatrix = (1, 0, 0, 1, 0, 0)) -> None:
        self.ctm = ctm

    @property
    def matrix(self) -> TransformationMatrixType:
        """
        Return the transformation matrix as a tuple of tuples in the form:

        ((a, b, 0), (c, d, 0), (e, f, 1))
        """
        return (
            (self.ctm[0], self.ctm[1], 0),
            (self.ctm[2], self.ctm[3], 0),
            (self.ctm[4], self.ctm[5], 1),
        )

    @staticmethod
    def compress(matrix: TransformationMatrixType) -> CompressedTransformationMatrix:
        """
        Compresses the transformation matrix into a tuple of (a, b, c, d, e, f).

        Args:
            matrix: The transformation matrix as a tuple of tuples.

        Returns:
            A tuple representing the transformation matrix as (a, b, c, d, e, f)

        """
        return (
            matrix[0][0],
            matrix[0][1],
            matrix[1][0],
            matrix[1][1],
            matrix[2][0],
            matrix[2][1],
        )

    def _to_cm(self) -> str:
        # Returns the cm operation string for the given transformation matrix
        return (
            f"{self.ctm[0]:.4f} {self.ctm[1]:.4f} {self.ctm[2]:.4f} "
            f"{self.ctm[3]:.4f} {self.ctm[4]:.4f} {self.ctm[5]:.4f} cm"
        )

    def transform(self, m: "Transformation") -> "Transformation":
        """
        Apply one transformation to another.

        Args:
            m: a Transformation to apply.

        Returns:
            A new ``Transformation`` instance

        Example:
            >>> from pypdf import PdfWriter, Transformation
            >>> height, width = 40, 50
            >>> page = PdfWriter().add_blank_page(800, 600)
            >>> op = Transformation((1, 0, 0, -1, 0, height)) # vertical mirror
            >>> op = Transformation().transform(Transformation((-1, 0, 0, 1, width, 0)))  # horizontal mirror
            >>> page.add_transformation(op)

        """
        ctm = Transformation.compress(matrix_multiply(self.matrix, m.matrix))
        return Transformation(ctm)

    def translate(self, tx: float = 0, ty: float = 0) -> "Transformation":
        """
        Translate the contents of a page.

        Args:
            tx: The translation along the x-axis.
            ty: The translation along the y-axis.

        Returns:
            A new ``Transformation`` instance

        """
        m = self.ctm
        return Transformation(ctm=(m[0], m[1], m[2], m[3], m[4] + tx, m[5] + ty))

    def scale(
        self, sx: Optional[float] = None, sy: Optional[float] = None
    ) -> "Transformation":
        """
        Scale the contents of a page towards the origin of the coordinate system.

        Typically, that is the lower-left corner of the page. That can be
        changed by translating the contents / the page boxes.

        Args:
            sx: The scale factor along the x-axis.
            sy: The scale factor along the y-axis.

        Returns:
            A new Transformation instance with the scaled matrix.

        """
        if sx is None and sy is None:
            raise ValueError("Either sx or sy must be specified")
        if sx is None:
            sx = sy
        if sy is None:
            sy = sx
        assert sx is not None
        assert sy is not None
        op: TransformationMatrixType = ((sx, 0, 0), (0, sy, 0), (0, 0, 1))
        ctm = Transformation.compress(matrix_multiply(self.matrix, op))
        return Transformation(ctm)

    def rotate(self, rotation: float) -> "Transformation":
        """
        Rotate the contents of a page.

        Args:
            rotation: The angle of rotation in degrees.

        Returns:
            A new ``Transformation`` instance with the rotated matrix.

        """
        rotation = math.radians(rotation)
        op: TransformationMatrixType = (
            (math.cos(rotation), math.sin(rotation), 0),
            (-math.sin(rotation), math.cos(rotation), 0),
            (0, 0, 1),
        )
        ctm = Transformation.compress(matrix_multiply(self.matrix, op))
        return Transformation(ctm)

    def __repr__(self) -> str:
        return f"Transformation(ctm={self.ctm})"

    @overload
    def apply_on(self, pt: list[float], as_object: bool = False) -> list[float]:
        ...

    @overload
    def apply_on(
        self, pt: tuple[float, float], as_object: bool = False
    ) -> tuple[float, float]:
        ...

    def apply_on(
        self,
        pt: Union[tuple[float, float], list[float]],
        as_object: bool = False,
    ) -> Union[tuple[float, float], list[float]]:
        """
        Apply the transformation matrix on the given point.

        Args:
            pt: A tuple or list representing the point in the form (x, y).
            as_object: If True, return items as FloatObject, otherwise as plain floats.

        Returns:
            A tuple or list representing the transformed point in the form (x', y')

        """
        typ = FloatObject if as_object else float
        pt1 = (
            typ(float(pt[0]) * self.ctm[0] + float(pt[1]) * self.ctm[2] + self.ctm[4]),
            typ(float(pt[0]) * self.ctm[1] + float(pt[1]) * self.ctm[3] + self.ctm[5]),
        )
        return list(pt1) if isinstance(pt, list) else pt1


@dataclass
class ImageFile:
    """
    Image within the PDF file. *This object is not designed to be built.*

    This object should not be modified except using :func:`ImageFile.replace` to replace the image with a new one.
    """

    name: str = ""
    """
    Filename as identified within the PDF file.

    .. warning::

        This value can contain arbitrary characters. Please make sure to sanitize it before
        using it to write the file content to the disk for example.
    """

    data: bytes = b""
    """
    Data as bytes.
    """

    image: Optional[Image] = None
    """
    Data as PIL image.
    """

    indirect_reference: Optional[IndirectObject] = None
    """
    Reference to the object storing the stream.
    """

    is_inline: bool = False
    """
    True if this is an inline image (~0~, ~1~, etc.).
    """

    is_displayed: bool = False
    """
    True if this image is displayed in the page content stream.
    """

    def replace(self, new_image: Image, **kwargs: Any) -> None:
        """
        Replace the image with a new PIL image.

        Args:
            new_image (PIL.Image.Image): The new PIL image to replace the existing image.
            **kwargs: Additional keyword arguments to pass to `Image.save()`.

        Raises:
            TypeError: If the image is inline or in a PdfReader.
            TypeError: If the image does not belong to a PdfWriter.
            TypeError: If `new_image` is not a PIL Image.

        Note:
            This method replaces the existing image with a new image.
            It is not allowed for inline images or images within a PdfReader.
            The `kwargs` parameter allows passing additional parameters
            to `Image.save()`, such as quality.

        """
        if pil_not_imported:
            raise ImportError(
                "pillow is required to do image extraction. "
                "It can be installed via 'pip install pypdf[image]'"
            )

        from ._reader import PdfReader  # noqa: PLC0415
        from .generic import DictionaryObject, PdfObject  # noqa: PLC0415
        from .generic._image_xobject import _xobj_to_image  # noqa: PLC0415

        if self.indirect_reference is None:
            raise TypeError("Cannot update an inline image.")
        if not hasattr(self.indirect_reference.pdf, "_id_translated"):
            raise TypeError("Cannot update an image not belonging to a PdfWriter.")
        if not isinstance(new_image, Image):
            raise TypeError("new_image shall be a PIL Image")
        b = BytesIO()
        new_image.save(b, "PDF", **kwargs)
        reader = PdfReader(b)
        page_image = reader.pages[0].images[0]
        assert page_image.indirect_reference is not None
        self.indirect_reference.pdf._objects[self.indirect_reference.idnum - 1] = (
            page_image.indirect_reference.get_object()
        )
        cast(
            PdfObject, self.indirect_reference.get_object()
        ).indirect_reference = self.indirect_reference
        # change the object attributes
        extension, byte_stream, img = _xobj_to_image(
            cast(DictionaryObject, self.indirect_reference.get_object()),
            pillow_parameters=kwargs,
        )
        assert extension is not None
        self.name = self.name[: self.name.rfind(".")] + extension
        self.data = byte_stream
        self.image = img

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, data: {_human_readable_bytes(len(self.data))})"

    def __repr__(self) -> str:
        return self.__str__()[:-1] + f", hash: {hash(self.data)})"


class VirtualListImages(Sequence[ImageFile]):
    """
    Provides access to images referenced within a page.
    Only one copy will be returned if the usage is used on the same page multiple times.
    See :func:`PageObject.images` for more details.
    """

    def __init__(
        self,
        ids_function: Callable[[], list[Union[str, list[str]]]],
        get_function: Callable[[Union[str, list[str], tuple[str]]], ImageFile],
    ) -> None:
        self.ids_function = ids_function
        self.get_function = get_function
        self.current = -1

    def __len__(self) -> int:
        return len(self.ids_function())

    def keys(self) -> list[Union[str, list[str]]]:
        return self.ids_function()

    def items(self) -> list[tuple[Union[str, list[str]], ImageFile]]:
        return [(x, self[x]) for x in self.ids_function()]

    @overload
    def __getitem__(self, index: Union[int, str, list[str]]) -> ImageFile:
        ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[ImageFile]:
        ...

    def __getitem__(
        self, index: Union[int, slice, str, list[str], tuple[str]]
    ) -> Union[ImageFile, Sequence[ImageFile]]:
        lst = self.ids_function()
        if isinstance(index, slice):
            indices = range(*index.indices(len(self)))
            lst = [lst[x] for x in indices]
            cls = type(self)
            return cls((lambda: lst), self.get_function)
        if isinstance(index, (str, list, tuple)):
            return self.get_function(index)
        if not isinstance(index, int):
            raise TypeError("Invalid sequence indices type")
        len_self = len(lst)
        if index < 0:
            # support negative indexes
            index += len_self
        if not (0 <= index < len_self):
            raise IndexError("Sequence index out of range")
        return self.get_function(lst[index])

    def __iter__(self) -> Iterator[ImageFile]:
        for i in range(len(self)):
            yield self[i]

    def __str__(self) -> str:
        p = [f"Image_{i}={n}" for i, n in enumerate(self.ids_function())]
        return f"[{', '.join(p)}]"


class PageObject(DictionaryObject):
    """
    PageObject represents a single page within a PDF file.

    Typically these objects will be created by accessing the
    :attr:`pages<pypdf.PdfReader.pages>` property of the
    :class:`PdfReader<pypdf.PdfReader>` class, but it is
    also possible to create an empty page with the
    :meth:`create_blank_page()<pypdf._page.PageObject.create_blank_page>` static method.

    Args:
        pdf: PDF file the page belongs to.
        indirect_reference: Stores the original indirect reference to
            this object in its source PDF

    """

    original_page: "PageObject"  # very local use in writer when appending

    def __init__(
        self,
        pdf: Optional[PdfCommonDocProtocol] = None,
        indirect_reference: Optional[IndirectObject] = None,
    ) -> None:
        DictionaryObject.__init__(self)
        self.pdf = pdf
        self._content_stream_images: Optional[dict[str, Optional[ImageFile]]] = None
        self.indirect_reference = indirect_reference
        if not is_null_or_none(indirect_reference):
            assert indirect_reference is not None, "mypy"
            self.update(cast(DictionaryObject, indirect_reference.get_object()))

    def hash_bin(self) -> int:
        """
        Used to detect modified object.

        Note: this function is overloaded to return the same results
        as a DictionaryObject.

        Returns:
            Hash considering type and value.

        """
        return hash(
            (DictionaryObject, tuple(((k, v.hash_bin()) for k, v in self.items())))
        )

    def hash_value_data(self) -> bytes:
        data = super().hash_value_data()
        data += f"{id(self)}".encode()
        return data

    @property
    def user_unit(self) -> float:
        """
        A read-only positive number giving the size of user space units.

        It is in multiples of 1/72 inch. Hence a value of 1 means a user
        space unit is 1/72 inch, and a value of 3 means that a user
        space unit is 3/72 inch.
        """
        return cast(float, self.get(PG.USER_UNIT, 1))

    @staticmethod
    def create_blank_page(
        pdf: Optional[PdfCommonDocProtocol] = None,
        width: Union[float, Decimal, None] = None,
        height: Union[float, Decimal, None] = None,
    ) -> "PageObject":
        """
        Return a new blank page.

        If ``width`` or ``height`` is ``None``, try to get the page size
        from the last page of *pdf*.

        Args:
            pdf: PDF file the page is within.
            width: The width of the new page expressed in default user
                space units.
            height: The height of the new page expressed in default user
                space units.

        Returns:
            The new blank page

        Raises:
            PageSizeNotDefinedError: if ``pdf`` is ``None`` or contains
                no page

        """
        page = PageObject(pdf)

        # Creates a new page (cf PDF Reference §7.7.3.3)
        page.__setitem__(NameObject(PG.TYPE), NameObject("/Page"))
        page.__setitem__(NameObject(PG.PARENT), NullObject())
        page.__setitem__(NameObject(PG.RESOURCES), DictionaryObject())
        if width is None or height is None:
            if pdf is not None and len(pdf.pages) > 0:
                lastpage = pdf.pages[len(pdf.pages) - 1]
                width = lastpage.mediabox.width
                height = lastpage.mediabox.height
            else:
                raise PageSizeNotDefinedError
        page.__setitem__(
            NameObject(PG.MEDIABOX), RectangleObject((0, 0, width, height))
        )

        return page

    def _get_ids_image(
        self,
        obj: Optional[DictionaryObject] = None,
        ancest: Optional[list[str]] = None,
        call_stack: Optional[list[Any]] = None,
    ) -> list[Union[str, list[str]]]:
        if call_stack is None:
            call_stack = []
        _i = getattr(obj, "indirect_reference", None)
        if _i in call_stack:
            return []
        call_stack.append(_i)
        if self._content_stream_images is None:
            self._content_stream_images = self._parse_images_from_content_stream()
        if obj is None:
            obj = self
        if ancest is None:
            ancest = []
        lst: list[Union[str, list[str]]] = []
        if (
                PG.RESOURCES not in obj or
                is_null_or_none(resources := cast(DictionaryObject, obj[PG.RESOURCES])) or
                RES.XOBJECT not in resources
        ):
            # Forms without XObject resources have no images inside them
            if len(ancest) > 0:
                return []
            # for inline images, cache dict entries are not None
            return [image_name for image_name, image_value in self._content_stream_images.items() if image_value]

        x_object = resources[RES.XOBJECT].get_object()
        if not isinstance(x_object, DictionaryObject):
            logger_warning(
                "XObject resources are not a dictionary: %(x_object)s",
                source=__name__,
                x_object=x_object,
            )
            return []

        # Iterate through all XObject resources
        for o in x_object:
            entry = x_object[o]
            # Skip non-stream objects (only process StreamObject)
            if not isinstance(entry, StreamObject):
                conti…14310 tokens truncated…ryObject()).get_object()
            if not isinstance(resources_dict, DictionaryObject):
                logger_warning(
                    "Page resources are not a dictionary: %(resources)s",
                    source=__name__,
                    resources=resources_dict,
                )
                resources_dict = DictionaryObject()
            if self.pdf is not None and (font_resources := _get_font_resources(resources_dict)):
                for font_name in font_resources:
                    font_object = font_resources[font_name].get_object()
                    if isinstance(font_object, DictionaryObject):
                        fonts[font_name] = Font.from_font_resource(font_object)

            parent = obj.get("/Parent", NullObject()).get_object()
            if not isinstance(parent, DictionaryObject):
                break
            obj = parent

        return fonts

    def _layout_mode_text(
        self,
        space_vertically: bool = True,
        scale_weight: float = 1.25,
        strip_rotated: bool = True,
        debug_path: Optional[Path] = None,
        font_height_weight: float = 1,
    ) -> str:
        """
        Get text preserving fidelity to source PDF text layout.

        Args:
            space_vertically: include blank lines inferred from y distance + font
                height. Defaults to True.
            scale_weight: multiplier for string length when calculating weighted
                average character width. Defaults to 1.25.
            strip_rotated: Removes text that is rotated w.r.t. to the page from
                layout mode output. Defaults to True.
            debug_path (Path | None): if supplied, must target a directory.
                creates the following files with debug information for layout mode
                functions if supplied:
                  - fonts.json: output of self._layout_mode_fonts
                  - tjs.json: individual text render ops with corresponding transform matrices
                  - bts.json: text render ops left justified and grouped by BT/ET operators
                  - bt_groups.json: BT/ET operations grouped by rendered y-coord (aka lines)
                Defaults to None.
            font_height_weight: multiplier for font height when calculating
                blank lines. Defaults to 1.

        Returns:
            str: multiline string containing page text in a fixed width format that
                closely adheres to the rendered layout in the source pdf.

        """
        fonts = self._layout_mode_fonts()
        if debug_path:  # pragma: no cover
            import json  # noqa: PLC0415

            debug_path.joinpath("fonts.json").write_text(
                json.dumps(fonts, indent=2, default=asdict),
                "utf-8"
            )

        contents = self.get("/Contents")
        if contents is not None:
            contents = contents.get_object()
        if not isinstance(contents, (ArrayObject, StreamObject)):
            # No content can be extracted (certainly an empty page).
            return ""

        ops = iter(ContentStream(contents, self.pdf, "bytes").operations)
        bt_groups = _layout_mode.text_show_operations(
            ops, fonts, strip_rotated, debug_path
        )

        if not bt_groups:
            return ""

        ty_groups = _layout_mode.y_coordinate_groups(bt_groups, debug_path)

        char_width = _layout_mode.fixed_char_width(bt_groups, scale_weight)

        return _layout_mode.fixed_width_page(ty_groups, char_width, space_vertically, font_height_weight)

    def extract_text(
        self,
        *args: Any,
        orientations: Union[int, tuple[int, ...]] = (0, 90, 180, 270),
        space_width: float = 200.0,
        visitor_operand_before: Optional[Callable[[Any, Any, Any, Any], None]] = None,
        visitor_operand_after: Optional[Callable[[Any, Any, Any, Any], None]] = None,
        visitor_text: Optional[Callable[[Any, Any, Any, Any, Any], None]] = None,
        extraction_mode: Literal["plain", "layout"] = "plain",
        **kwargs: Any,
    ) -> str:
        """
        Locate all text drawing commands, in the order they are provided in the
        content stream, and extract the text.

        This works well for some PDF files, but poorly for others, depending on
        the generator used. This will be refined in the future.

        Do not rely on the order of text coming out of this function, as it
        will change if this function is made more sophisticated.

        Arabic and Hebrew are extracted in the correct order.
        If required a custom RTL range of characters can be defined;
        see function set_custom_rtl.

        Additionally you can provide visitor methods to get informed on all
        operations and all text objects.
        For example in some PDF files this can be useful to parse tables.

        Args:
            orientations: list of orientations extract_text will look for
                default = (0, 90, 180, 270)
                note: currently only 0 (up),90 (turned left), 180 (upside down),
                270 (turned right)
                Silently ignored in "layout" mode.
            space_width: force default space width
                if not extracted from font (default: 200)
                Silently ignored in "layout" mode.
            visitor_operand_before: function to be called before processing an operation.
                It has four arguments: operator, operand-arguments,
                current transformation matrix and text matrix.
                Ignored with a warning in "layout" mode.
            visitor_operand_after: function to be called after processing an operation.
                It has four arguments: operator, operand-arguments,
                current transformation matrix and text matrix.
                Ignored with a warning in "layout" mode.
            visitor_text: function to be called when extracting some text at some position.
                It has five arguments: text, current transformation matrix,
                text matrix, font-dictionary and font-size.
                The font-dictionary may be None in case of unknown fonts.
                If not None it may e.g. contain key "/BaseFont" with value "/Arial,Bold".
                Ignored with a warning in "layout" mode.
            extraction_mode (Literal["plain", "layout"]): "plain" for legacy functionality,
                "layout" for experimental layout mode functionality.
                NOTE: orientations, space_width, and visitor_* parameters are NOT respected
                in "layout" mode.

        kwargs:
            layout_mode_space_vertically (bool): include blank lines inferred from
                y distance + font height. Defaults to True.
            layout_mode_scale_weight (float): multiplier for string length when calculating
                weighted average character width. Defaults to 1.25.
            layout_mode_strip_rotated (bool): layout mode does not support rotated text.
                Set to False to include rotated text anyway. If rotated text is discovered,
                layout will be degraded and a warning will result. Defaults to True.
            layout_mode_debug_path (Path | None): if supplied, must target a directory.
                creates the following files with debug information for layout mode
                functions if supplied:

                  - fonts.json: output of self._layout_mode_fonts
                  - tjs.json: individual text render ops with corresponding transform matrices
                  - bts.json: text render ops left justified and grouped by BT/ET operators
                  - bt_groups.json: BT/ET operations grouped by rendered y-coord (aka lines)
            layout_mode_font_height_weight (float): multiplier for font height when calculating
                blank lines. Defaults to 1.

        Returns:
            The extracted text

        """
        if extraction_mode not in ["plain", "layout"]:
            raise ValueError(f"Invalid text extraction mode '{extraction_mode}'")
        if extraction_mode == "layout":
            for visitor in (
                "visitor_operand_before",
                "visitor_operand_after",
                "visitor_text",
            ):
                if locals()[visitor]:
                    logger_warning(
                        "Argument %(visitor)s is ignored in layout mode",
                        source=__name__,
                        visitor=visitor,
                    )
            return self._layout_mode_text(
                space_vertically=kwargs.get("layout_mode_space_vertically", True),
                scale_weight=kwargs.get("layout_mode_scale_weight", 1.25),
                strip_rotated=kwargs.get("layout_mode_strip_rotated", True),
                debug_path=kwargs.get("layout_mode_debug_path"),
                font_height_weight=kwargs.get("layout_mode_font_height_weight", 1)
            )
        if len(args) >= 1:
            if isinstance(args[0], str):
                if len(args) >= 3:
                    if isinstance(args[2], (tuple, int)):
                        orientations = args[2]
                    else:
                        raise TypeError(f"Invalid positional parameter {args[2]}")
                if len(args) >= 4:
                    if isinstance(args[3], (float, int)):
                        space_width = args[3]
                    else:
                        raise TypeError(f"Invalid positional parameter {args[3]}")
            elif isinstance(args[0], (tuple, int)):
                orientations = args[0]
                if len(args) >= 2:
                    if isinstance(args[1], (float, int)):
                        space_width = args[1]
                    else:
                        raise TypeError(f"Invalid positional parameter {args[1]}")
            else:
                raise TypeError(f"Invalid positional parameter {args[0]}")

        if isinstance(orientations, int):
            orientations = (orientations,)

        return self._extract_text(
            self,
            self.pdf,
            orientations,
            space_width,
            PG.CONTENTS,
            visitor_operand_before,
            visitor_operand_after,
            visitor_text,
        )

    def extract_xform_text(
        self,
        xform: EncodedStreamObject,
        orientations: tuple[int, ...] = (0, 90, 270, 360),
        space_width: float = 200.0,
        visitor_operand_before: Optional[Callable[[Any, Any, Any, Any], None]] = None,
        visitor_operand_after: Optional[Callable[[Any, Any, Any, Any], None]] = None,
        visitor_text: Optional[Callable[[Any, Any, Any, Any, Any], None]] = None,
        *,
        known_ids: Optional[set[int]] = None,
        traversal_state: Optional[Any] = None
    ) -> str:
        """
        Extract text from an XObject.

        Args:
            xform:
            orientations:
            space_width:  force default space width (if not extracted from font (default 200)
            visitor_operand_before:
            visitor_operand_after:
            visitor_text:
            known_ids:
            traversal_state:

        Returns:
            The extracted text

        """
        # The type hint would have to use an internal type otherwise, which is not desired.
        assert traversal_state is None or isinstance(traversal_state, _TraversalState)
        return self._extract_text(
            xform,
            self.pdf,
            orientations,
            space_width,
            None,
            visitor_operand_before,
            visitor_operand_after,
            visitor_text,
            known_ids=known_ids,
            traversal_state=traversal_state,
        )

    def _get_fonts(self) -> tuple[set[str], set[str]]:
        """
        Get the names of embedded fonts and unembedded fonts.

        Returns:
            A tuple (set of embedded fonts, set of unembedded fonts)

        """
        obj = self.get_object()
        assert isinstance(obj, DictionaryObject)
        fonts: set[str] = set()
        embedded: set[str] = set()
        fonts, embedded = _get_fonts_walk(obj, fonts, embedded)
        unembedded = fonts - embedded
        return embedded, unembedded

    mediabox = _create_rectangle_accessor(PG.MEDIABOX, ())
    """A :class:`RectangleObject<pypdf.generic.RectangleObject>`, expressed in
    default user space units, defining the boundaries of the physical medium on
    which the page is intended to be displayed or printed."""

    cropbox = _create_rectangle_accessor("/CropBox", (PG.MEDIABOX,))
    """
    A :class:`RectangleObject<pypdf.generic.RectangleObject>`, expressed in
    default user space units, defining the visible region of default user
    space.

    When the page is displayed or printed, its contents are to be clipped
    (cropped) to this rectangle and then imposed on the output medium in some
    implementation-defined manner. Default value: same as
    :attr:`mediabox<mediabox>`.
    """

    bleedbox = _create_rectangle_accessor("/BleedBox", ("/CropBox", PG.MEDIABOX))
    """A :class:`RectangleObject<pypdf.generic.RectangleObject>`, expressed in
    default user space units, defining the region to which the contents of the
    page should be clipped when output in a production environment."""

    trimbox = _create_rectangle_accessor("/TrimBox", ("/CropBox", PG.MEDIABOX))
    """A :class:`RectangleObject<pypdf.generic.RectangleObject>`, expressed in
    default user space units, defining the intended dimensions of the finished
    page after trimming."""

    artbox = _create_rectangle_accessor("/ArtBox", ("/CropBox", PG.MEDIABOX))
    """A :class:`RectangleObject<pypdf.generic.RectangleObject>`, expressed in
    default user space units, defining the extent of the page's meaningful
    content as intended by the page's creator."""

    @property
    def annotations(self) -> Optional[ArrayObject]:
        if "/Annots" not in self:
            return None
        annotations = self["/Annots"].get_object()
        if not isinstance(annotations, ArrayObject):
            logger_warning(
                "Annotations are not an array: %(annotations)s",
                source=__name__,
                annotations=annotations,
            )
            return None
        return annotations

    @annotations.setter
    def annotations(self, value: Optional[ArrayObject]) -> None:
        """
        Set the annotations array of the page.

        Typically you do not want to set this value, but append to it.
        If you append to it, remember to add the object first to the writer
        and only add the indirect object.
        """
        if value is None:
            if "/Annots" not in self:
                return
            del self[NameObject("/Annots")]
        else:
            self[NameObject("/Annots")] = value

    def add_action(self, trigger: PageTrigger, action: Action) -> None:
        """
        Add an action which will launch on the given trigger event of this page.

        Args:
            trigger: The action trigger to use.
            action: The action to be done.

        Example:
            >>> from pypdf import PdfWriter
            >>> from pypdf.actions import JavaScript, PageTrigger
            >>> writer = PdfWriter()
            >>> page = writer.add_blank_page(595, 842)
            >>> # Display the page number when the page is opened
            >>> page.add_action(PageTrigger("open"), JavaScript("app.alert('This is page ' + this.pageNum);"))
            >>> # Display the page number when the page is closed
            >>> page.add_action(PageTrigger("close"), JavaScript("app.alert('This is page ' + this.pageNum);"))
        """
        return Action._create_new(self, trigger, action)

    def delete_action(self, trigger: PageTrigger) -> None:
        """
        Delete all actions associated with an open or close trigger event of this page.

        Args:
            trigger: An open or close trigger.

        Example:
            >>> from pypdf import PdfWriter
            >>> from pypdf.actions import JavaScript, PageTrigger
            >>> writer = PdfWriter()
            >>> page = writer.add_blank_page(595, 842)
            >>> page.add_action(PageTrigger("open"), JavaScript("app.alert('This is page ' + this.pageNum);"))
            >>> page.add_action(PageTrigger("close"), JavaScript("app.alert('This is page ' + this.pageNum);"))
            >>> # Delete all actions triggered by a page open
            >>> page.delete_action(PageTrigger("open"))
            >>> # Delete all actions triggered by a page close
            >>> page.delete_action(PageTrigger("close"))
        """
        return Action._delete(self, trigger)


class _VirtualList(Sequence[PageObject]):
    def __init__(
        self,
        length_function: Callable[[], int],
        get_function: Callable[[int], PageObject],
    ) -> None:
        self.length_function = length_function
        self.get_function = get_function
        self.current = -1

    def __len__(self) -> int:
        return self.length_function()

    @overload
    def __getitem__(self, index: int) -> PageObject:
        ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[PageObject]:
        ...

    def __getitem__(
        self, index: Union[int, slice]
    ) -> Union[PageObject, Sequence[PageObject]]:
        if isinstance(index, slice):
            indices = range(*index.indices(len(self)))
            cls = type(self)
            return cls(indices.__len__, lambda idx: self[indices[idx]])
        if not isinstance(index, int):
            raise TypeError("Sequence indices must be integers")
        len_self = len(self)
        if index < 0:
            # support negative indexes
            index += len_self
        if not (0 <= index < len_self):
            raise IndexError("Sequence index out of range")
        return self.get_function(index)

    def __delitem__(self, index: Union[int, slice]) -> None:
        if isinstance(index, slice):
            r = list(range(*index.indices(len(self))))
            # pages have to be deleted from last to first
            r.sort()
            r.reverse()
            for p in r:
                del self[p]  # recursive call
            return
        if not isinstance(index, int):
            raise TypeError("Index must be integers")
        len_self = len(self)
        if index < 0:
            # support negative indexes
            index += len_self
        if not (0 <= index < len_self):
            raise IndexError("Index out of range")
        ind = self[index].indirect_reference
        assert ind is not None
        parent: Optional[PdfObject] = cast(DictionaryObject, ind.get_object()).get(
            "/Parent", None
        )
        first = True
        while parent is not None:
            parent = cast(DictionaryObject, parent.get_object())
            try:
                i = cast(ArrayObject, parent["/Kids"]).index(ind)
                del cast(ArrayObject, parent["/Kids"])[i]
                first = False
                try:
                    assert ind is not None
                    del ind.pdf.flattened_pages[index]  # case of page in a Reader
                except MemoryError:  # pragma: no cover  # TODO: BLE001
                    raise
                except Exception:  # pragma: no cover
                    pass
                if "/Count" in parent:
                    parent[NameObject("/Count")] = NumberObject(
                        cast(int, parent["/Count"]) - 1
                    )
                if len(cast(ArrayObject, parent["/Kids"])) == 0:
                    # No more objects in this part of this subtree
                    ind = parent.indirect_reference
                parent = parent.get("/Parent", None)
            except ValueError as exception:  # from index
                if first:
                    raise PdfReadError(f"Page not found in page tree: {ind}") from exception
                break

    def __iter__(self) -> Iterator[PageObject]:
        for i in range(len(self)):
            yield self[i]

    def __str__(self) -> str:
        p = [f"PageObject({i})" for i in range(self.length_function())]
        return f"[{', '.join(p)}]"


def _get_fonts_walk(
    obj: DictionaryObject,
    fnt: set[str],
    emb: set[str],
) -> tuple[set[str], set[str]]:
    """
    Get the set of all fonts and all embedded fonts.

    Args:
        obj: Page resources dictionary
        fnt: font
        emb: embedded fonts

    Returns:
        A tuple (fnt, emb)

    If there is a key called 'BaseFont', that is a font that is used in the document.
    If there is a key called 'FontName' and another key in the same dictionary object
    that is called 'FontFilex' (where x is null, 2, or 3), then that fontname is
    embedded.

    We create and add to two sets, fnt = fonts used and emb = fonts embedded.

    """
    fontkeys = ("/FontFile", "/FontFile2", "/FontFile3")

    def process_font(f: PdfObject) -> None:
        nonlocal fnt, emb
        f = cast(DictionaryObject, f.get_object())  # to be sure
        if "/BaseFont" in f:
            fnt.add(cast(str, f["/BaseFont"]))

        if (
            ("/CharProcs" in f)
            or (
                "/FontDescriptor" in f
                and any(
                    x in cast(DictionaryObject, f["/FontDescriptor"]) for x in fontkeys
                )
            )
            or (
                "/DescendantFonts" in f
                and "/FontDescriptor"
                in cast(
                    DictionaryObject,
                    cast(ArrayObject, f["/DescendantFonts"])[0].get_object(),
                )
                and any(
                    x
                    in cast(
                        DictionaryObject,
                        cast(
                            DictionaryObject,
                            cast(ArrayObject, f["/DescendantFonts"])[0].get_object(),
                        )["/FontDescriptor"],
                    )
                    for x in fontkeys
                )
            )
        ):
            # the list comprehension ensures there is FontFile
            try:
                emb.add(cast(str, f["/BaseFont"]))
            except KeyError:
                emb.add("(" + cast(str, f["/Subtype"]) + ")")

    if "/DR" in obj and "/Font" in cast(DictionaryObject, obj["/DR"]):
        for f in cast(
            DictionaryObject, cast(DictionaryObject, obj["/DR"])["/Font"]
        ).values():
            process_font(f)
    if "/Resources" in obj:
        if "/Font" in cast(DictionaryObject, obj["/Resources"]):
            for f in cast(
                DictionaryObject, cast(DictionaryObject, obj["/Resources"])["/Font"]
            ).values():
                process_font(f)
        if "/XObject" in cast(DictionaryObject, obj["/Resources"]):
            for x in cast(
                DictionaryObject, cast(DictionaryObject, obj["/Resources"])["/XObject"]
            ).values():
                _get_fonts_walk(cast(DictionaryObject, x.get_object()), fnt, emb)
    if "/Annots" in obj:
        for a in cast(ArrayObject, obj["/Annots"]):
            _get_fonts_walk(cast(DictionaryObject, a.get_object()), fnt, emb)
    if "/AP" in obj:
        if (
            cast(DictionaryObject, cast(DictionaryObject, obj["/AP"])["/N"]).get(
                "/Type"
            )
            == "/XObject"
        ):
            _get_fonts_walk(
                cast(DictionaryObject, cast(DictionaryObject, obj["/AP"])["/N"]),
                fnt,
                emb,
            )
        else:
            for a in cast(DictionaryObject, cast(DictionaryObject, obj["/AP"])["/N"]):
                _get_fonts_walk(cast(DictionaryObject, a), fnt, emb)
    return fnt, emb  # return the sets for each page
