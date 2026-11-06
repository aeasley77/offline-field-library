Warning: truncated output (original token count: 35662)
Total output lines: 3586

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

import decimal
import enum
import hashlib
import re
import struct
import sys
from collections.abc import Iterable, Mapping, Sequence
from io import BytesIO, FileIO, IOBase
from itertools import compress
from pathlib import Path
from re import Pattern
from types import TracebackType
from typing import (
    IO,
    Any,
    Callable,
    Literal,
    Optional,
    Union,
    cast,
)

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ._doc_common import DocumentInformation, PdfDocCommon
from ._encryption import EncryptAlgorithm, Encryption
from ._page import PageObject, Transformation
from ._page_labels import nums_clear_range, nums_insert, nums_next
from ._reader import PdfReader
from ._utils import (
    StrByteType,
    StreamType,
    _get_max_pdf_version_header,
    deprecate_with_replacement,
    deprecation_no_replacement,
    logger_warning,
)
from .actions import Action, JavaScript
from .constants import AnnotationDictionaryAttributes as AA
from .constants import (
    CatalogAttributes,
    Core,
    GoToActionArguments,
    ImageType,
    InteractiveFormDictEntries,
    OutlineFontFlag,
    PageLabelStyle,
    PagesAttributes,
    UserAccessPermissions,
)
from .constants import FieldDictionaryAttributes as FA
from .constants import PageAttributes as PG
from .constants import TrailerKeys as TK
from .errors import LimitReachedError, PdfReadError, PyPdfError
from .generic import (
    PAGE_FIT,
    ArrayObject,
    BooleanObject,
    ByteStringObject,
    ContentStream,
    Destination,
    DictionaryObject,
    EmbeddedFile,
    Fit,
    FloatObject,
    IndirectObject,
    NamedReferenceLink,
    NameObject,
    NullObject,
    NumberObject,
    PdfObject,
    RectangleObject,
    ReferenceLink,
    StreamObject,
    TextStringObject,
    TreeObject,
    ViewerPreferences,
    create_string_object,
    extract_links,
    hex_to_rgb,
    is_null_or_none,
)
from .generic._appearance_stream import TextStreamAppearance
from .pagerange import PageRange, PageRangeSpec
from .types import (
    AnnotationSubtype,
    BorderArrayType,
    LayoutType,
    OutlineItemType,
    OutlineType,
    PagemodeType,
)
from .xmp import XmpInformation

ALL_DOCUMENT_PERMISSIONS = UserAccessPermissions.all()


class ObjectDeletionFlag(enum.IntFlag):
    NONE = 0
    TEXT = enum.auto()
    LINKS = enum.auto()
    ATTACHMENTS = enum.auto()
    OBJECTS_3D = enum.auto()
    ALL_ANNOTATIONS = enum.auto()
    XOBJECT_IMAGES = enum.auto()
    INLINE_IMAGES = enum.auto()
    DRAWING_IMAGES = enum.auto()
    IMAGES = XOBJECT_IMAGES | INLINE_IMAGES | DRAWING_IMAGES


def _rolling_checksum(stream: BytesIO, blocksize: int = 65536) -> str:
    hash_object = hashlib.md5(usedforsecurity=False)
    for block in iter(lambda: stream.read(blocksize), b""):
        hash_object.update(block)
    return hash_object.hexdigest()


class PdfWriter(PdfDocCommon):
    """
    Write a PDF file out, given pages produced by another class or through
    cloning a PDF file during initialization.

    Typically data is added from a :class:`PdfReader<pypdf.PdfReader>`.

    Args:
        clone_from: identical to fileobj (for compatibility)

        incremental: If true, loads the document and set the PdfWriter in incremental mode.

            When writing incrementally, the original document is written first and new/modified
            content is appended. To be used for signed document/forms to keep signature valid.

        full: If true, loads all the objects (always full if incremental = True).
            This parameter may allow loading large PDFs.

        strict: If true, pypdf will raise an exception if a PDF does not follow the specification.
            If false, pypdf will try to be forgiving and do something reasonable, but it will log
            a warning message. It is a best-effort approach.

        keep_initial_header: If true, the PDF header of the cloned document is kept
            when using ``clone_from`` in non-incremental mode.

    """

    incremental: bool
    """
    Returns if the PdfWriter object has been started in incremental mode.
    """

    _objects: list[Optional[PdfObject]]
    """
    The indirect objects in the PDF.
    For the incremental case, it will be filled with None
    in clone_reader_document_root.
    """

    _id_translated: dict[int, dict[Union[int, Literal["PreventGC"]], Any]]
    """
    List of already translated IDs.
    dict[id(pdf)][(idnum, generation)]
    """

    _reader: Optional[PdfReader]
    """
    The document being appended to, in incremental mode only.
    """

    def __init__(
        self,
        fileobj: Union[PdfReader, StrByteType, Path, None] = "",
        clone_from: Union[PdfReader, StrByteType, Path, None] = None,
        incremental: bool = False,
        full: bool = False,
        strict: bool = False,
        *,
        keep_initial_header: bool = False,
        incremental_clone_object_count_limit: Optional[int] = 500_000,
        incremental_clone_object_id_limit: Optional[int] = 1_000_000,
    ) -> None:
        self.strict = strict
        """
        If true, pypdf will raise an exception if a PDF does not follow the specification.
        If false, pypdf will try to be forgiving and do something reasonable, but it will log
        a warning message. It is a best-effort approach.
        """

        self.incremental = incremental or full

        self._objects = []

        self._original_hash: list[int] = []
        """
        List of hashes after import; used to identify changes.
        """

        self._idnum_hash: dict[bytes, tuple[IndirectObject, list[IndirectObject]]] = {}
        """
        Maps hash values of indirect objects to the list of IndirectObjects.
        This is used for compression.
        """

        self._id_translated = {}

        self._info_obj: Optional[PdfObject]
        """The PDF files's document information dictionary,
        defined by Info in the PDF file's trailer dictionary."""

        self._reader = None

        self._ID: Union[ArrayObject, None] = None
        """The PDF file identifier,
        defined by the ID in the PDF file's trailer dictionary."""

        self._unresolved_links: list[tuple[ReferenceLink, ReferenceLink]] = []
        "Tracks links in pages added to the writer for resolving later."
        self._merged_in_pages: dict[Optional[IndirectObject], Optional[IndirectObject]] = {}
        "Tracks pages added to the writer and what page they turned into."

        # Security parameters.
        self._incremental_clone_object_count_limit = (
            incremental_clone_object_count_limit
            if isinstance(incremental_clone_object_count_limit, int)
            else sys.maxsize
        )
        self._incremental_clone_object_id_limit = (
            incremental_clone_object_id_limit if isinstance(incremental_clone_object_id_limit, int) else sys.maxsize
        )

        if self.incremental:
            if isinstance(fileobj, (str, Path)):
                with open(fileobj, "rb") as f:
                    fileobj = BytesIO(f.read(-1))
            if isinstance(fileobj, BytesIO):
                fileobj = PdfReader(fileobj)
            if not isinstance(fileobj, PdfReader):
                raise PyPdfError("Invalid type for incremental mode")
            self._reader = fileobj  # prev content is in _reader.stream
            self._header = fileobj.pdf_header.encode()
            self._readonly = True  # TODO: to be analysed
        else:
            self._header = b"%PDF-1.3"
            self._info_obj = self._add_object(
                DictionaryObject(
                    {NameObject("/Producer"): create_string_object("pypdf")}
                )
            )

        def _get_clone_from(
            fileobj: Union[PdfReader, str, Path, IO[Any], BytesIO, None],
            clone_from: Union[PdfReader, str, Path, IO[Any], BytesIO, None],
        ) -> Union[PdfReader, str, Path, IO[Any], BytesIO, None]:
            if isinstance(fileobj, (str, Path, IO, BytesIO)) and (
                fileobj == "" or clone_from is not None
            ):
                return clone_from
            cloning = True
            if isinstance(fileobj, (str, Path)):
                fileobj_path = Path(fileobj)
                if not fileobj_path.exists() or fileobj_path.stat().st_size == 0:
                    cloning = False
            elif isinstance(fileobj, (IOBase, BytesIO)):
                t = fileobj.tell()
                if fileobj.seek(0, 2) == 0:
                    cloning = False
                fileobj.seek(t, 0)
            if cloning:
                clone_from = fileobj
            return clone_from

        clone_from = _get_clone_from(fileobj, clone_from)
        # To prevent overwriting
        self.temp_fileobj = fileobj
        self.fileobj = ""
        self._with_as_usage = False
        self._cloned = False
        # The root of our page tree node
        pages = DictionaryObject(
            {
                NameObject(PagesAttributes.TYPE): NameObject("/Pages"),
                NameObject(PagesAttributes.COUNT): NumberObject(0),
                NameObject(PagesAttributes.KIDS): ArrayObject(),
            }
        )
        self.flattened_pages = []
        self._encryption: Optional[Encryption] = None
        self._encrypt_entry: Optional[DictionaryObject] = None

        if clone_from is not None:
            if not isinstance(clone_from, PdfReader):
                clone_from = PdfReader(clone_from)
            self.clone_document_from_reader(clone_from)
            self._cloned = True
            if keep_initial_header and not self.incremental:
                self._header = clone_from.pdf_header.encode()
        else:
            self._pages = self._add_object(pages)
            self._root_object = DictionaryObject(
                {
                    NameObject(PagesAttributes.TYPE): NameObject(Core.CATALOG),
                    NameObject(Core.PAGES): self._pages,
                }
            )
            self._add_object(self._root_object)
        if full and not incremental:
            self.incremental = False
        if isinstance(self._ID, list):
            if isinstance(self._ID[0], TextStringObject):
                self._ID[0] = ByteStringObject(self._ID[0].get_original_bytes())
            if isinstance(self._ID[1], TextStringObject):
                self._ID[1] = ByteStringObject(self._ID[1].get_original_bytes())

    # for commonality
    @property
    def is_encrypted(self) -> bool:
        """
        Read-only boolean property showing whether this PDF file is encrypted.

        Note that this property, if true, will remain true even after the
        :meth:`decrypt()<pypdf.PdfReader.decrypt>` method is called.
        """
        return False

    @property
    def root_object(self) -> DictionaryObject:
        """
        Provide direct access to PDF Structure.

        Note:
            Recommended only for read access.

        """
        return self._root_object

    @property
    def _info(self) -> Optional[DictionaryObject]:
        """
        Provide access to "/Info". Standardized with PdfReader.

        Returns:
            /Info Dictionary; None if the entry does not exist

        """
        return (
            None
            if self._info_obj is None
            else cast(DictionaryObject, self._info_obj.get_object())
        )

    @_info.setter
    def _info(self, value: Optional[Union[IndirectObject, DictionaryObject]]) -> None:
        if value is None:
            try:
                self._objects[self._info_obj.indirect_reference.idnum - 1] = None  # type: ignore[union-attr]
            except (KeyError, AttributeError):
                pass
            self._info_obj = None
        else:
            if self._info_obj is None:
                self._info_obj = self._add_object(DictionaryObject())
            obj = cast(DictionaryObject, self._info_obj.get_object())
            obj.clear()
            obj.update(cast(DictionaryObject, value.get_object()))

    @property
    def xmp_metadata(self) -> Optional[XmpInformation]:
        """XMP (Extensible Metadata Platform) data."""
        return cast(XmpInformation, self.root_object.xmp_metadata)

    @xmp_metadata.setter
    def xmp_metadata(self, value: Union[XmpInformation, bytes, None]) -> None:
        """XMP (Extensible Metadata Platform) data."""
        if value is None:
            if "/Metadata" in self.root_object:
                del self.root_object["/Metadata"]
            return

        metadata = self.root_object.get("/Metadata", None)
        if not isinstance(metadata, IndirectObject):
            if metadata is not None:
                del self.root_object["/Metadata"]
            metadata_stream = StreamObject()
            stream_reference = self._add_object(metadata_stream)
            self.root_object[NameObject("/Metadata")] = stream_reference
        else:
            metadata_stream = cast(StreamObject, metadata.get_object())

        if isinstance(value, XmpInformation):
            bytes_data = value.stream.get_data()
        else:
            bytes_data = value
        metadata_stream.set_data(bytes_data)

    @property
    def with_as_usage(self) -> bool:
        deprecation_no_replacement("with_as_usage", "5.0")

    @with_as_usage.setter
    def with_as_usage(self, value: bool) -> None:
        deprecation_no_replacement("with_as_usage", "5.0")

    def __enter__(self) -> Self:
        """Store how writer is initialized by 'with'."""
        c: bool = self._cloned
        t = self.temp_fileobj
        self.__init__()  # type: ignore[misc]
        self._cloned = c
        self._with_as_usage = True
        self.fileobj = t  # type: ignore[assignment]
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Write data to the fileobj."""
        if self.fileobj and not self._cloned:
            self.write(self.fileobj)

    @property
    def pdf_header(self) -> str:
        """
        Read/Write property of the PDF header that is written.

        This should be something like ``'%PDF-1.5'``. It is recommended to set
        the lowest version that supports all features which are used within the
        PDF file.

        Note: `pdf_header` returns a string but accepts bytes or str for writing
        """
        return self._header.decode()

    @pdf_header.setter
    def pdf_header(self, new_header: Union[str, bytes]) -> None:
        if isinstance(new_header, str):
            new_header = new_header.encode()
        self._header = new_header

    def _add_object(self, obj: PdfObject) -> IndirectObject:
        if (
            getattr(obj, "indirect_reference", None) is not None
            and obj.indirect_reference.pdf == self  # type: ignore[union-attr]
        ):
            return obj.indirect_reference  # type: ignore[return-value]
        # check for /Contents in Pages (/Contents in annotations are strings)
        if isinstance(obj, DictionaryObject) and isinstance(
            obj.get(PG.CONTENTS, None), (ArrayObject, DictionaryObject)
        ):
            obj[NameObject(PG.CONTENTS)] = self._add_object(obj[PG.CONTENTS])
        self._objects.append(obj)
        obj.indirect_reference = IndirectObject(len(self._objects), 0, self)
        return obj.indirect_reference

    def get_object(
        self,
        indirect_reference: Union[int, IndirectObject],
    ) -> PdfObject:
        if isinstance(indirect_reference, int):
            obj = self._objects[indirect_reference - 1]
        elif indirect_reference.pdf != self:
            raise ValueError("PDF must be self")
        else:
            obj = self._objects[indirect_reference.idnum - 1]
        if obj is None:
            raise PdfReadError(f"Object {indirect_reference!r} not found!")
        return obj

    def _replace_object(
        self,
        indirect_reference: Union[int, IndirectObject],
        obj: PdfObject,
    ) -> PdfObject:
        if isinstance(indirect_reference, IndirectObject):
            if indirect_reference.pdf != self:
                raise ValueError("PDF must be self")
            indirect_reference = indirect_reference.idnum
        gen = self._objects[indirect_reference - 1].indirect_reference.generation  # type: ignore[union-attr]
        if (
            getattr(obj, "indirect_reference", None) is not None
            and obj.indirect_reference.pdf != self  # type: ignore[union-attr]
        ):
            obj = obj.clone(self)
        self._objects[indirect_reference - 1] = obj
        obj.indirect_reference = IndirectObject(indirect_reference, gen, self)

        assert isinstance(obj, PdfObject), "mypy"
        return obj

    def _add_page(
        self,
        page: PageObject,
        index: int,
        excluded_keys: Iterable[str] = (),
    ) -> PageObject:
        if not isinstance(page, PageObject) or page.get(PagesAttributes.TYPE, None) != Core.PAGE:
            raise ValueError("Invalid page object")
        assert self.flattened_pages is not None, "mypy"
        page_org = page
        excluded_keys = list(excluded_keys)
        excluded_keys += [PagesAttributes.PARENT, "/StructParents"]
        # Acrobat does not accept two indirect references pointing on the same
        # page; therefore in order to add multiple copies of the same
        # page, we need to create a new dictionary for the page, however the
        # objects below (including content) are not duplicated:
        try:  # delete an already existing page
            del self._id_translated[id(page_org.indirect_reference.pdf)][  # type: ignore[union-attr]
                page_org.indirect_reference.idnum  # type: ignore[union-attr]
            ]
        except MemoryError:  # pragma: no cover  # TODO: BLE001
            raise
        except Exception:
            pass

        page = cast(
            "PageObject", page_org.clone(self, False, excluded_keys).get_object()
        )
        if page_org.pdf is not None:
            other = page_org.pdf.pdf_header
            self.pdf_header = _get_max_pdf_version_header(self.pdf_header, other)

        node, idx = self._get_page_in_node(index)
        page[NameObject(PagesAttributes.PARENT)] = node.indirect_reference

        if idx >= 0:
            cast(ArrayObject, node[PagesAttributes.KIDS]).insert(idx, page.indirect_reference)
            self.flattened_pages.insert(index, page)
        else:
            cast(ArrayObject, node[PagesAttributes.KIDS]).append(page.indirect_reference)
            self.flattened_pages.append(page)
        current: Optional[PdfObject] = node
        recurse = 0
        while not is_null_or_none(current):
            assert current is not None, "mypy"  # guarded by is_null_or_none
            node_dict = cast(DictionaryObject, current.get_object())
            node_dict[NameObject(PagesAttributes.COUNT)] = NumberObject(cast(int, node_dict[PagesAttributes.COUNT]) + 1)
            current = node_dict.get(PagesAttributes.PARENT, None)
            recurse += 1
            if recurse > 1000:
                raise PyPdfError("Too many recursive calls!")

        if page_org.pdf is not None:
            # the page may contain links to other pages, and those other
            # pages may or may not already be added.  we store the
            # information we need, so that we can resolve the references
            # later.
            if "/Annots" not in excluded_keys:
                self._unresolved_links.extend(extract_links(page, page_org))
            self._merged_in_pages[page_org.indirect_reference] = page.indirect_reference

        return page

    def set_need_appearances_writer(self, state: bool = True) -> None:
        """
        Sets the "NeedAppearances" flag in the PDF writer.

        The "NeedAppearances" flag indicates whether the appearance dictionary
        for form fields should be automatically generated by the PDF viewer or
        if the embedded appearance should be used.

        Args:
            state: The actual value of the NeedAppearances flag.

        Returns:
            None

        """
        # See §12.7.2 and §7.7.2 for more information:
        # https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf
        try:
            # get the AcroForm tree
            if CatalogAttributes.ACRO_FORM not in self._root_object:
                self._root_object[
                    NameObject(CatalogAttributes.ACRO_FORM)
                ] = self._add_object(DictionaryObject())

            need_appearances = NameObject(InteractiveFormDictEntries.NeedAppearances)
            cast(DictionaryObject, self._root_object[CatalogAttributes.ACRO_FORM])[
                need_appearances
            ] = BooleanObject(state)
        except MemoryError:  # pragma: no cover  # TODO: BLE001
            raise
        except Exception as exc:  # pragma: no cover
            logger_warning(
                "set_need_appearances_writer(%(state)s) catch : %(exc)s",
                source=__name__,
                state=state,
                exc=exc,
            )

    def create_viewer_preferences(self) -> ViewerPreferences:
        o = ViewerPreferences()
        self._root_object[
            NameObject(CatalogAttributes.VIEWER_PREFERENCES)
        ] = self._add_object(o)
        return o

    def add_page(
        self,
        page: PageObject,
        excluded_keys: Iterable[str] = (),
    ) -> PageObject:
        """
        Add a page to this PDF file.

        Recommended for advanced usage including the adequate excluded_keys.

        The page is usually acquired from a :class:`PdfReader<pypdf.PdfReader>`
        instance.

        Args:
            page: The page to add to the document. Should be
                an instance of :class:`PageObject<pypdf._page.PageObject>`
            excluded_keys:

        Returns:
            The added PageObject.

        """
        assert self.flattened_pages is not None, "mypy"
        return self._add_page(page, len(self.flattened_pages), excluded_keys)

    def insert_page(
        self,
        page: PageObject,
        index: int = 0,
        excluded_keys: Iterable[str] = (),
    ) -> PageObject:
        """
        In…23662 tokens truncated…_object = cast("PageObject", page.get_object())
                if "/B" not in page_object:
                    page_object[NameObject("/B")] = ArrayObject()
                cast("ArrayObject", page_object["/B"]).append(
                    new_article.indirect_reference
                )

            current_article = cast("DictionaryObject", current_article["/N"])
            if current_article == first_article:
                new_article[NameObject("/N")] = new_first.indirect_reference  # type: ignore[index]
                new_first[NameObject("/V")] = new_article.indirect_reference  # type: ignore[union-attr]
                current_article = None

        assert new_thread.indirect_reference is not None
        return new_thread.indirect_reference

    def add_filtered_articles(
        self,
        fltr: Union[
            Pattern[Any], str
        ],  # thread entry from the reader's array of threads
        pages: dict[int, PageObject],
        reader: PdfReader,
    ) -> None:
        """
        Add articles matching the defined criteria.

        Args:
            fltr:
            pages:
            reader:

        """
        if isinstance(fltr, str):
            fltr = re.compile(fltr)
        elif not isinstance(fltr, Pattern):
            fltr = re.compile("")
        for p in pages.values():
            pp = p.original_page
            for a in pp.get("/B", ()):
                a_obj = a.get_object()
                if is_null_or_none(a_obj):
                    continue
                thr = a_obj.get("/T")
                if thr is None:
                    continue
                thr = thr.get_object()
                if thr.indirect_reference.idnum not in self._id_translated[
                    id(reader)
                ] and fltr.search((thr.get("/I", {})).get("/Title", "")):
                    self._add_articles_thread(thr, pages, reader)

    def _get_cloned_page(
        self,
        page: Union[IndirectObject, PageObject, NullObject, int, None],
        pages: dict[int, PageObject],
        reader: PdfReader,
    ) -> Optional[IndirectObject]:
        if isinstance(page, NullObject):
            return None
        if isinstance(page, int):
            # An explicit destination may reference the target page by its
            # (zero-based) index in the source document rather than by an
            # indirect reference; this is what `Link(target_page_index=...)`
            # produces. Resolve the index through the reader's page list so it
            # can be remapped like a regular page reference. A destination that
            # points past the end of the source document is dropped.
            try:
                page = reader.pages[page].indirect_reference
            except IndexError:
                return None
        if isinstance(page, DictionaryObject) and page.get("/Type", "") == "/Page":
            _i = page.indirect_reference
        elif isinstance(page, IndirectObject):
            _i = page
        try:
            return pages[_i.idnum].indirect_reference  # type: ignore[union-attr]
        except MemoryError:  # pragma: no cover  # TODO: BLE001
            raise
        except Exception:
            return None

    def _insert_filtered_annotations(
        self,
        *,
        annots: Union[IndirectObject, list[PdfObject], None],
        page: PageObject,
        pages: dict[int, PageObject],
        reader: PdfReader,
        parent_fields: Optional[dict[int, DictionaryObject]] = None,
    ) -> list[Destination]:
        outlist = ArrayObject()
        if isinstance(annots, IndirectObject):
            annots = cast("list[Any]", annots.get_object())
        if annots is None:
            return outlist
        if not isinstance(annots, list):
            logger_warning(
                "Expected list of annotations, got %(annots)s of type %(annots_type)s.",
                source=__name__,
                annots=annots,
                annots_type=annots.__class__.__name__,
            )
            return outlist
        for an in annots:
            ano = cast("DictionaryObject", an.get_object())
            if (
                ano.get("/Subtype") != "/Link"
                or "/A" not in ano
                or cast("DictionaryObject", ano["/A"])["/S"] != "/GoTo"  # type: ignore[comparison-overlap]
                or "/Dest" in ano
            ):
                if (
                    parent_fields is not None
                    and ano.get("/Subtype") == "/Widget"
                    and isinstance(ano.get("/Parent"), IndirectObject)
                ):
                    outlist.append(self._clone_widget_annotation(ano, parent_fields))
                elif "/Dest" not in ano:
                    outlist.append(self._add_object(ano.clone(self)))
                else:
                    d = ano["/Dest"]
                    if isinstance(d, str):
                        # it is a named dest
                        if str(d) in self.get_named_dest_root():
                            outlist.append(ano.clone(self).indirect_reference)
                    else:
                        if not isinstance(d, ArrayObject) or not d:
                            continue
                        p = self._get_cloned_page(d[0], pages, reader)
                        if p is not None:
                            anc = ano.clone(self, ignore_fields=("/Dest",))
                            anc[NameObject("/Dest")] = ArrayObject([p, *d[1:]])
                            outlist.append(self._add_object(anc))
            else:
                d = cast("DictionaryObject", ano["/A"]).get("/D", NullObject())
                if is_null_or_none(d):
                    continue
                if isinstance(d, str):
                    # it is a named dest
                    if str(d) in self.get_named_dest_root():
                        outlist.append(ano.clone(self).indirect_reference)
                else:
                    if not isinstance(d, ArrayObject) or not d:
                        continue
                    p = self._get_cloned_page(d[0], pages, reader)
                    if p is not None:
                        anc = ano.clone(self, ignore_fields=("/D",))
                        cast("DictionaryObject", anc["/A"])[
                            NameObject("/D")
                        ] = ArrayObject([p, *d[1:]])
                        outlist.append(self._add_object(anc))
        return outlist

    def _clone_widget_annotation(
        self, annotation: DictionaryObject, parent_fields: dict[int, DictionaryObject]
    ) -> IndirectObject:
        """
        Clone a widget annotation and link it to its parent fields.

        Cloning ``/Parent`` directly would also clone the ``/Kids`` of the
        parent fields, and with them the widgets and pages of sibling fields
        which are not part of the merge. Instead, the parent fields are cloned
        without ``/Kids`` and collected in ``parent_fields``, so that their kids
        can be set by :meth:`_set_cloned_kids` once all annotations are cloned.
        """
        clone = annotation.clone(self, ignore_fields=(1, "/Parent"))
        source, target = annotation, clone
        while isinstance(source.get("/Parent"), IndirectObject):
            parent_reference = cast(IndirectObject, source.get("/Parent"))
            source_parent = parent_reference.get_object()
            if not isinstance(source_parent, DictionaryObject):
                break
            parent = source_parent.clone(self, ignore_fields=(1, "/Kids", 1, "/Parent"))
            target[NameObject("/Parent")] = parent.indirect_reference
            if parent_reference.idnum in parent_fields:
                # The ancestors have already been linked.
                break
            parent_fields[parent_reference.idnum] = source_parent
            source, target = source_parent, parent
        assert clone.indirect_reference is not None
        return clone.indirect_reference

    def _set_cloned_kids(self, parent_fields: dict[int, DictionaryObject], reader: PdfReader) -> None:
        """Set the ``/Kids`` of the cloned parent fields to the cloned kids, in their original order."""
        translated = self._id_translated.get(id(reader), {})
        for idnum, source_parent in parent_fields.items():
            kids = source_parent.get("/Kids", ArrayObject())
            parent = cast(DictionaryObject, self.get_object(translated[idnum]))
            parent[NameObject("/Kids")] = ArrayObject(
                IndirectObject(translated[kid.idnum], 0, self)
                for kid in cast(ArrayObject, kids)
                if isinstance(kid, IndirectObject) and kid.idnum in translated
            )

    def _get_filtered_outline(
        self,
        *,
        node: Any,
        pages: dict[int, PageObject],
        reader: PdfReader,
        visited: Optional[set[int]] = None,
    ) -> list[Destination]:
        """
        Extract outline item entries that are part of the specified page set.

        Returns:
            A list of destination objects.

        """
        if visited is None:
            visited = set()
        new_outline: list[Destination] = []
        if node is None:
            return new_outline
        node = node.get_object()
        if is_null_or_none(node):
            node = DictionaryObject()
        if not isinstance(node, DictionaryObject):
            logger_warning("Outline node is not a dictionary: %(node)s", source=__name__, node=node)
            return new_outline

        if node.get("/Type", "") == "/Outlines" or "/Title" not in node:
            node_id = id(node)
            if node_id in visited:
                logger_warning("Detected cycle in outlines.", source=__name__)
                return []
            visited.add(node_id)

            node = node.get("/First", None)
            if node is not None:
                node = node.get_object()
                new_outline += self._get_filtered_outline(node=node, pages=pages, reader=reader, visited=visited)
        else:
            cloned_page: Union[IndirectObject, NullObject, None]
            while True:
                node = node.get_object()
                if not isinstance(node, DictionaryObject):
                    logger_warning("Outline node is not a dictionary: %(node)s", source=__name__, node=node)
                    break
                node_id = id(node)
                if node_id in visited:
                    logger_warning("Detected cycle in outlines.", source=__name__)
                    break
                visited.add(node_id)

                destination = cast("Destination", reader._build_outline_item(node))
                cloned_page = self._get_cloned_page(cast("PageObject", destination["/Page"]), pages, reader)
                if cloned_page is None:
                    cloned_page = NullObject()
                destination[NameObject("/Page")] = cloned_page
                if "/First" in node:
                    destination._filtered_children = self._get_filtered_outline(
                        node=node["/First"], pages=pages, reader=reader, visited=visited
                    )
                else:
                    destination._filtered_children = []
                if (
                    not isinstance(cloned_page, NullObject)
                    or len(destination._filtered_children) > 0
                ):
                    new_outline.append(destination)

                if "/Next" not in node:
                    break
                node = node["/Next"]
        return new_outline

    def _clone_outline(self, dest: Destination) -> TreeObject:
        n_ol = TreeObject()
        self._add_object(n_ol)
        n_ol[NameObject("/Title")] = TextStringObject(dest["/Title"])
        if not isinstance(dest["/Page"], NullObject):
            if dest.node is not None and "/A" in dest.node:
                n_ol[NameObject("/A")] = dest.node["/A"].clone(self)
            else:
                n_ol[NameObject("/Dest")] = dest.dest_array
        # TODO: /SE
        if dest.node is not None:
            n_ol[NameObject("/F")] = NumberObject(dest.node.get("/F", 0))
            color = dest.node.get("/C", NullObject()).get_object()
            if not isinstance(color, list):
                color = [FloatObject(0.0), FloatObject(0.0), FloatObject(0.0)]
            n_ol[NameObject("/C")] = ArrayObject(color)
        return n_ol

    def _insert_filtered_outline(
        self,
        outlines: list[Destination],
        parent: Union[TreeObject, IndirectObject],
        before: Union[TreeObject, IndirectObject, None] = None,
    ) -> None:
        for dest in outlines:
            # TODO: can be improved to keep A and SE entries (ignored for the moment)
            # with np=self.add_outline_item_destination(dest,parent,before)
            if dest.get("/Type", "") == "/Outlines" or "/Title" not in dest:
                np = parent
            else:
                np = self._clone_outline(dest)
                cast(TreeObject, parent.get_object()).insert_child(np, before, self)
            self._insert_filtered_outline(dest._filtered_children, np, None)

    def close(self) -> None:
        """Implemented for API harmonization."""
        return

    def find_outline_item(
        self,
        outline_item: Union[IndirectObject, str],
        root: Optional[OutlineType] = None,
        *,
        visited: Optional[set[int]] = None,
    ) -> Optional[list[int]]:
        if root is None:
            outline = self.get_outline_root()
        else:
            outline = cast("TreeObject", root)
        if visited is None:
            visited = set()

        index = 0
        while outline is not None:
            if (
                outline.indirect_reference == outline_item
                or outline.get("/Title", None) == outline_item
            ):
                return [index]

            outline_id = id(outline)
            if outline_id in visited:
                raise LimitReachedError("Detected cyclic outline hierarchy.")
            visited.add(outline_id)

            if "/First" in outline:
                result = self.find_outline_item(
                    outline_item=outline_item,
                    root=cast(OutlineType, outline["/First"]),
                    visited=visited,
                )
                if result:
                    return ([index] if "/Title" in outline else []) + result
            if "/Next" in outline:
                index += 1
                outline = cast(TreeObject, outline["/Next"])
            else:
                return None
        raise PyPdfError("This line is theoretically unreachable.")  # pragma: no cover

    def reset_translation(
        self, reader: Union[PdfReader, IndirectObject, None] = None
    ) -> None:
        """
        Reset the translation table between reader and the writer object.

        Late cloning will create new independent objects.

        Args:
            reader: PdfReader or IndirectObject referencing a PdfReader object.
                if set to None or omitted, all tables will be reset.

        """
        if reader is None:
            self._id_translated = {}
        elif isinstance(reader, PdfReader):
            try:
                del self._id_translated[id(reader)]
            except MemoryError:  # pragma: no cover  # TODO: BLE001
                raise
            except Exception:
                pass
        elif isinstance(reader, IndirectObject):
            try:
                del self._id_translated[id(reader.pdf)]
            except MemoryError:  # pragma: no cover  # TODO: BLE001
                raise
            except Exception:
                pass
        else:
            raise TypeError(f"Invalid parameter {reader}")

    def set_page_label(
        self,
        page_index_from: int,
        page_index_to: int,
        style: Optional[PageLabelStyle] = None,
        prefix: Optional[str] = None,
        start: Optional[int] = 0,
    ) -> None:
        """
        Set a page label to a range of pages.

        Page indexes must be given starting from 0.
        Labels must have a style, a prefix or both.
        If a range is not assigned any page label, a decimal label starting from 1 is applied.

        Args:
            page_index_from: page index of the beginning of the range starting from 0
            page_index_to: page index of the beginning of the range starting from 0
            style: The numbering style to be used for the numeric portion of each page label:

                       * ``/D`` Decimal Arabic numerals
                       * ``/R`` Uppercase Roman numerals
                       * ``/r`` Lowercase Roman numerals
                       * ``/A`` Uppercase letters (A to Z for the first 26 pages,
                         AA to ZZ for the next 26, and so on)
                       * ``/a`` Lowercase letters (a to z for the first 26 pages,
                         aa to zz for the next 26, and so on)

            prefix: The label prefix for page labels in this range.
            start:  The value of the numeric portion for the first page label
                    in the range.
                    Subsequent pages are numbered sequentially from this value,
                    which must be greater than or equal to 1.
                    Default value: 1.

        """
        if style is None and prefix is None:
            raise ValueError("At least one of style and prefix must be given")
        if style is not None and style not in tuple(PageLabelStyle):
            raise ValueError(
                f"style must be one of: {', '.join(PageLabelStyle)}, got {style!r}"
            )
        if page_index_from < 0:
            raise ValueError("page_index_from must be greater or equal than 0")
        if page_index_to < page_index_from:
            raise ValueError(
                "page_index_to must be greater or equal than page_index_from"
            )
        if page_index_to >= len(self.pages):
            raise ValueError("page_index_to exceeds number of pages")
        if start is not None and start != 0 and start < 1:
            raise ValueError("If given, start must be greater or equal than one")

        self._set_page_label(page_index_from, page_index_to, style, prefix, start)

    def _set_page_label(
        self,
        page_index_from: int,
        page_index_to: int,
        style: Optional[PageLabelStyle] = None,
        prefix: Optional[str] = None,
        start: Optional[int] = 0,
    ) -> None:
        """
        Set a page label to a range of pages.

        Page indexes must be given starting from 0.
        Labels must have a style, a prefix or both.
        If a range is not assigned any page label a decimal label starting from 1 is applied.

        Args:
            page_index_from: page index of the beginning of the range starting from 0
            page_index_to: page index of the beginning of the range starting from 0
            style:  The numbering style to be used for the numeric portion of each page label:
                        /D Decimal Arabic numerals
                        /R Uppercase Roman numerals
                        /r Lowercase Roman numerals
                        /A Uppercase letters (A to Z for the first 26 pages,
                           AA to ZZ for the next 26, and so on)
                        /a Lowercase letters (a to z for the first 26 pages,
                           aa to zz for the next 26, and so on)
            prefix: The label prefix for page labels in this range.
            start:  The value of the numeric portion for the first page label
                    in the range.
                    Subsequent pages are numbered sequentially from this value,
                    which must be greater than or equal to 1. Default value: 1.

        """
        default_page_label = DictionaryObject()
        default_page_label[NameObject("/S")] = NameObject("/D")

        new_page_label = DictionaryObject()
        if style is not None:
            new_page_label[NameObject("/S")] = NameObject(style)
        if prefix is not None:
            new_page_label[NameObject("/P")] = TextStringObject(prefix)
        if start != 0:
            new_page_label[NameObject("/St")] = NumberObject(start)

        if NameObject(CatalogAttributes.PAGE_LABELS) not in self._root_object:
            nums = ArrayObject()
            nums_insert(NumberObject(0), default_page_label, nums)
            page_labels = TreeObject()
            page_labels[NameObject("/Nums")] = nums
            self._root_object[NameObject(CatalogAttributes.PAGE_LABELS)] = page_labels

        page_labels = cast(
            TreeObject, self._root_object[NameObject(CatalogAttributes.PAGE_LABELS)]
        )
        nums = cast(ArrayObject, page_labels[NameObject("/Nums")])

        nums_insert(NumberObject(page_index_from), new_page_label, nums)
        nums_clear_range(NumberObject(page_index_from), page_index_to, nums)
        next_label_pos, *_ = nums_next(NumberObject(page_index_from), nums)
        if next_label_pos != page_index_to + 1 and page_index_to + 1 < len(self.pages):
            nums_insert(NumberObject(page_index_to + 1), default_page_label, nums)

        page_labels[NameObject("/Nums")] = nums
        self._root_object[NameObject(CatalogAttributes.PAGE_LABELS)] = page_labels

    def _repr_mimebundle_(
        self,
        include: Union[Iterable[str], None] = None,
        exclude: Union[Iterable[str], None] = None,
    ) -> dict[str, Any]:
        """
        Integration into Jupyter Notebooks.

        This method returns a dictionary that maps a mime-type to its
        representation.

        .. seealso::

           https://ipython.readthedocs.io/en/stable/config/integrating.html
        """
        pdf_data = BytesIO()
        self.write(pdf_data)
        data = {
            "application/pdf": pdf_data,
        }

        if include is not None:
            # Filter representations based on include list
            data = {k: v for k, v in data.items() if k in include}

        if exclude is not None:
            # Remove representations based on exclude list
            data = {k: v for k, v in data.items() if k not in exclude}

        return data


def _pdf_objectify(obj: Union[dict[str, Any], str, float, list[Any]]) -> PdfObject:
    if isinstance(obj, PdfObject):
        return obj
    if isinstance(obj, dict):
        to_add = DictionaryObject()
        for key, value in obj.items():
            to_add[NameObject(key)] = _pdf_objectify(value)
        return to_add
    if isinstance(obj, str):
        if obj.startswith("/"):
            return NameObject(obj)
        return TextStringObject(obj)
    if isinstance(obj, (float, int)):
        return FloatObject(obj)
    if isinstance(obj, list):
        return ArrayObject(_pdf_objectify(i) for i in obj)
    raise NotImplementedError(
        f"{type(obj)=} could not be cast to a PdfObject"
    )


def _create_outline_item(
    action_ref: Union[IndirectObject, None],
    title: str,
    color: Union[tuple[float, float, float], str, None],
    italic: bool,
    bold: bool,
) -> TreeObject:
    outline_item = TreeObject()
    if action_ref is not None:
        outline_item[NameObject("/A")] = action_ref
    outline_item.update(
        {
            NameObject("/Title"): create_string_object(title),
        }
    )
    if color:
        if isinstance(color, str):
            color = hex_to_rgb(color)
        outline_item.update(
            {NameObject("/C"): ArrayObject([FloatObject(c) for c in color])}
        )
    if italic or bold:
        format_flag = 0
        if italic:
            format_flag += OutlineFontFlag.italic
        if bold:
            format_flag += OutlineFontFlag.bold
        outline_item.update({NameObject("/F"): NumberObject(format_flag)})
    return outline_item
