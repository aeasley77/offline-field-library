Warning: truncated output (original token count: 19543)
Total output lines: 2049

# Copyright (c) 2006, Mathieu Fenniak
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

__author__ = "Mathieu Fenniak"
__author_email__ = "biziqe@mathieu.fenniak.net"

import logging
import os
import re
import sys
from collections.abc import Iterable, Sequence
from io import BytesIO
from math import ceil
from typing import (
    Any,
    Callable,
    NamedTuple,
    Optional,
    Union,
    cast,
)

from .. import get_configuration
from .._protocols import PdfReaderProtocol, PdfWriterProtocol, XmpInformationProtocol
from .._utils import (
    WHITESPACES,
    BinaryStreamType,
    StreamType,
    deprecation_no_replacement,
    logger_warning,
    read_non_whitespace,
    read_until_regex,
    read_until_whitespace,
    skip_over_comment,
    skip_over_comments,
)
from ..constants import (
    CheckboxRadioButtonAttributes,
    FieldDictionaryAttributes,
    OutlineFontFlag,
    StreamAttributes,
)
from ..constants import FilterTypes as FT
from ..constants import TypArguments as TA
from ..constants import TypFitArguments as TF
from ..errors import STREAM_TRUNCATED_PREMATURELY, LimitReachedError, PdfReadError, PdfStreamError
from ._base import (
    BooleanObject,
    ByteStringObject,
    FloatObject,
    IndirectObject,
    NameObject,
    NullObject,
    NumberObject,
    PdfObject,
    TextStringObject,
    is_null_or_none,
)
from ._fit import Fit
from ._image_inline import (
    extract_inline__ascii85_decode,
    extract_inline__ascii_hex_decode,
    extract_inline__dct_decode,
    extract_inline__run_length_decode,
    extract_inline_default,
)
from ._utils import StreamParsingBudget, read_hex_string_from_stream, read_string_from_stream

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

logger = logging.getLogger(__name__)

IndirectPattern = re.compile(rb"[+-]?(\d+)\s+(\d+)\s+R[^a-zA-Z]")

# Direct objects of these types are neither streams nor indirect objects.
# Large arrays consist mostly of them, for example in the /ParentTree of the
# structure tree, so the clone loops check the exact type first and skip the
# slower isinstance() checks.
_SCALAR_TYPES = frozenset(
    (BooleanObject, ByteStringObject, FloatObject, NameObject, NullObject, NumberObject, TextStringObject)
)


class ArrayObject(list[Any], PdfObject):
    def replicate(
        self,
        pdf_dest: PdfWriterProtocol,
    ) -> "ArrayObject":
        arr = cast(
            "ArrayObject",
            self._reference_clone(ArrayObject(), pdf_dest, False),
        )
        for data in self:
            if hasattr(data, "replicate"):
                arr.append(data.replicate(pdf_dest))
            else:
                arr.append(data)
        return arr

    def clone(
        self,
        pdf_dest: PdfWriterProtocol,
        force_duplicate: bool = False,
        ignore_fields: Optional[Sequence[Union[str, int]]] = (),
    ) -> "ArrayObject":
        """Clone object into pdf_dest."""
        try:
            if self.indirect_reference.pdf == pdf_dest and not force_duplicate:  # type: ignore[union-attr]
                return self
        except MemoryError:  # pragma: no cover  # TODO: BLE001
            raise
        except Exception:
            pass
        arr = cast(
            "ArrayObject",
            self._reference_clone(ArrayObject(), pdf_dest, force_duplicate=True),
        )
        for data in self:
            if type(data) in _SCALAR_TYPES:
                # Same as the generic case below, but without the isinstance() checks.
                arr.append(data.clone(pdf_dest, force_duplicate, ignore_fields))
            elif isinstance(data, StreamObject):
                dup = data._reference_clone(
                    data.clone(pdf_dest, force_duplicate, ignore_fields),
                    pdf_dest,
                    force_duplicate,
                )
                arr.append(dup.indirect_reference)
            elif isinstance(data, IndirectObject) and isinstance(resolved := data.get_object(), StreamObject):
                dup = data._reference_clone(
                    resolved.clone(pdf_dest, force_duplicate=True, ignore_fields=ignore_fields),
                    pdf_dest,
                    force_duplicate,
                )
                arr.append(dup.indirect_reference)
            elif hasattr(data, "clone"):
                arr.append(data.clone(pdf_dest, force_duplicate, ignore_fields))
            else:
                arr.append(data)
        return arr

    def hash_bin(self) -> int:
        """
        Used to detect modified object.

        Returns:
            Hash considering type and value.

        """
        return hash((self.__class__, tuple(x.hash_bin() for x in self)))

    def items(self) -> Iterable[Any]:
        """Emulate DictionaryObject.items for a list (index, object)."""
        return enumerate(self)

    def _to_lst(self, lst: Any) -> list[Any]:
        # Convert to list, internal
        result: list[Any]
        if isinstance(lst, (list, tuple, set)):
            result = list(lst)
        elif isinstance(lst, PdfObject):
            result = [lst]
        elif isinstance(lst, str):
            if lst[0] == "/":
                result = [NameObject(lst)]
            else:
                result = [TextStringObject(lst)]
        elif isinstance(lst, bytes):
            result = [ByteStringObject(lst)]
        else:  # for numbers,...
            result = [lst]
        return result

    def __add__(self, lst: Any) -> "ArrayObject":
        """
        Allow extension by adding list or add one element only

        Args:
            lst: any list, tuples are extended the list.
            other types(numbers,...) will be appended.
            if str is passed it will be converted into TextStringObject
            or NameObject (if starting with "/")
            if bytes is passed it will be converted into ByteStringObject

        Returns:
            ArrayObject with all elements

        """
        temp = ArrayObject(self)
        temp.extend(self._to_lst(lst))
        return temp

    def __iadd__(self, lst: Any) -> Self:
        """
         Allow extension by adding list or add one element only

        Args:
            lst: any list, tuples are extended the list.
            other types(numbers,...) will be appended.
            if str is passed it will be converted into TextStringObject
            or NameObject (if starting with "/")
            if bytes is passed it will be converted into ByteStringObject

        """
        self.extend(self._to_lst(lst))
        return self

    def __isub__(self, lst: Any) -> Self:
        """Allow to remove items"""
        for x in self._to_lst(lst):
            try:
                index = self.index(x)
                del self[index]
            except ValueError:
                pass
        return self

    def write_to_stream(
        self, stream: StreamType, encryption_key: Union[str, bytes, None] = None
    ) -> None:
        if encryption_key is not None:  # deprecated
            deprecation_no_replacement(
                "the encryption_key parameter of write_to_stream", "5.0.0"
            )
        stream.write(b"[")
        for data in self:
            stream.write(b" ")
            data.write_to_stream(stream)
        stream.write(b" ]")

    @staticmethod
    def _check_limits(*, remaining_elements: int, parsing_budget: Optional[StreamParsingBudget]) -> int:
        remaining_elements -= 1
        if remaining_elements < 0:
            raise LimitReachedError("Reached maximum array element count.")
        if parsing_budget is not None:
            parsing_budget.remaining_budget -= 1
            if parsing_budget.remaining_budget < 0:
                raise LimitReachedError("Reached maximum number of tokens.")
        return remaining_elements

    @staticmethod
    def read_from_stream(
        stream: StreamType,
        pdf: Optional[PdfReaderProtocol],
        forced_encoding: Union[str, list[str], dict[int, str], None] = None,
        *,
        parsing_budget: Optional[StreamParsingBudget] = None,
    ) -> "ArrayObject":
        arr = ArrayObject()
        tmp = stream.read(1)
        if tmp != b"[":
            raise PdfReadError("Could not read array")
        remaining_elements = get_configuration().array_maximum_element_count
        while True:
            # skip leading whitespace
            tok = stream.read(1)
            while tok.isspace() or tok in WHITESPACES:
                tok = stream.read(1)
            if tok == b"":
                break
            if tok == b"%":
                stream.seek(-1, 1)
                skip_over_comment(stream)
                continue
            # check for array ending
            if tok == b"]":
                break

            remaining_elements = ArrayObject._check_limits(
                remaining_elements=remaining_elements, parsing_budget=parsing_budget
            )
            if tok == b"n":
                # Shortcut for null, as some arrays consist mostly of nulls
                rest = stream.read(3)
                if rest == b"ull":
                    arr.append(NullObject())
                    continue
                stream.seek(-len(rest), 1)
            stream.seek(-1, 1)
            # read and append object
            arr.append(read_object(stream, pdf, forced_encoding, parsing_budget=parsing_budget))
        return arr


class DictionaryObject(dict[Any, Any], PdfObject):
    def replicate(
        self,
        pdf_dest: PdfWriterProtocol,
    ) -> "DictionaryObject":
        d__ = cast(
            "DictionaryObject",
            self._reference_clone(self.__class__(), pdf_dest, False),
        )
        for k, v in self.items():
            d__[k.replicate(pdf_dest)] = (
                v.replicate(pdf_dest) if hasattr(v, "replicate") else v
            )
        return d__

    def clone(
        self,
        pdf_dest: PdfWriterProtocol,
        force_duplicate: bool = False,
        ignore_fields: Optional[Sequence[Union[str, int]]] = (),
    ) -> "DictionaryObject":
        """Clone object into pdf_dest."""
        try:
            if self.indirect_reference.pdf == pdf_dest and not force_duplicate:  # type: ignore[union-attr]
                return self
        except MemoryError:  # pragma: no cover  # TODO: BLE001
            raise
        except Exception:
            pass

        visited: set[tuple[int, int]] = set()  # (idnum, generation)
        d__ = cast(
            "DictionaryObject",
            self._reference_clone(self.__class__(), pdf_dest, force_duplicate),
        )
        if ignore_fields is None:
            ignore_fields = []
        if len(d__.keys()) == 0:
            d__._clone(self, pdf_dest, force_duplicate, ignore_fields, visited)
        return d__

    def _clone(
        self,
        src: "DictionaryObject",
        pdf_dest: PdfWriterProtocol,
        force_duplicate: bool,
        ignore_fields: Optional[Sequence[Union[str, int]]],
        visited: set[tuple[int, int]],  # (idnum, generation)
    ) -> None:
        """
        Update the object from src.

        Args:
            src: "DictionaryObject":
            pdf_dest:
            force_duplicate:
            ignore_fields:

        """
        # First we remove the ignore_fields
        # that are for a limited number of levels
        assert ignore_fields is not None
        ignore_fields = list(ignore_fields)
        x = 0
        while x < len(ignore_fields):
            if isinstance(ignore_fields[x], int):
                if cast(int, ignore_fields[x]) <= 0:
                    del ignore_fields[x]
                    del ignore_fields[x]
                    continue
                ignore_fields[x] -= 1  # type:ignore
            x += 1
        #  Check if this is a chain list, we need to loop to prevent recur
        if any(
            field not in ignore_fields
            and field in src
            and isinstance(src.raw_get(field), IndirectObject)
            and isinstance(src[field], DictionaryObject)
            and (
                src.get("/Type", None) is None
                or cast(DictionaryObject, src[field]).get("/Type", None) is None
                or src.get("/Type", None)
                == cast(DictionaryObject, src[field]).get("/Type", None)
            )
            for field in ["/Next", "/Prev", "/N", "/V"]
        ):
            ignore_fields = list(ignore_fields)
            for lst in (("/Next", "/Prev"), ("/N", "/V")):
                for k in lst:
                    objs = []
                    if (
                        k in src
                        and k not in self
                        and isinstance(src.raw_get(k), IndirectObject)
                        and isinstance(src[k], DictionaryObject)
                        # If need to go further the idea is to check
                        # that the types are the same
                        and (
                            src.get("/Type", None) is None
                            or cast(DictionaryObject, src[k]).get("/Type", None) is None
                            or src.get("/Type", None)
                            == cast(DictionaryObject, src[k]).get("/Type", None)
                        )
                    ):
                        cur_obj: Optional[DictionaryObject] = cast(
                            "DictionaryObject", src[k]
                        )
                        prev_obj: Optional[DictionaryObject] = self
                        while cur_obj is not None:
                            source_reference = cur_obj.indirect_reference
                            clon = cast(
                                "DictionaryObject",
                                cur_obj._reference_clone(
                                    cur_obj.__class__(), pdf_dest, force_duplicate
                                ),
                            )
                            # Check to see if we've previously processed our item
                            if source_reference is not None:
                                source_idnum = source_reference.idnum
                                source_generation = source_reference.generation
                                if (source_idnum, source_generation) in visited:
                                    cur_obj = None
                                    break
                                visited.add((source_idnum, source_generation))
                            objs.append((cur_obj, clon))
                            assert prev_obj is not None
                            prev_obj[NameObject(k)] = clon.indirect_reference
                            prev_obj = clon
                            try:
                                if cur_obj == src:
                                    cur_obj = None
                                else:
                                    cur_obj = cast("DictionaryObject", cur_obj[k])
                            except MemoryError:  # pragma: no cover  # TODO: BLE001
                                raise
                            except Exception:
                                cur_obj = None
                        for s, c in objs:
                            c._clone(
                                s, pdf_dest, force_duplicate, ignore_fields, visited
                            )

        for k, v in src.items():
            if k not in ignore_fields:
                # The type check does not change the result. It only skips the
                # slower isinstance() check for the most common values.
                if type(v) not in _SCALAR_TYPES and isinstance(v, StreamObject):
                    if not hasattr(v, "indirect_reference"):
                        v.indirect_reference = None
                    vv = v.clone(pdf_dest, force_duplicate, ignore_fields)
                    assert vv.indirect_reference is not None
                    self[k.clone(pdf_dest)] = vv.indirect_reference
                elif k not in self:
                    self[NameObject(k)] = (
                        v.clone(pdf_dest, force_duplicate, ignore_fields)
                        if hasattr(v, "clone")
                        else v
                    )

    def hash_bin(self) -> int:
        """
        Used to detect modified object.

        Returns:
            Hash considering type and value.

        """
        return hash(
            (self.__class__, tuple(((k, v.hash_bin()) for k, v in self.items())))
        )

    def raw_get(self, key: Any) -> Any:
        return dict.__getitem__(self, key)

    def get_inherited(self, key: str, default: Any = None) -> Any:
        """
        Returns the value of a key or from the parent if not found.
        If not found returns default.

        Args:
            key: string identifying the field to return

            default: default value to return

        Returns:
            Current key or inherited one, otherwise default value.

        """
        current = self
        visited: set[int] = set()

        while True:
            # Detect cyclic parent references
            obj_id = id(current)
            if obj_id in visited:
                raise LimitReachedError(f"Detected cycle in /Parent hierarchy when retrieving value for key {key!r}.")
            visited.add(obj_id)

            if key in current:
                return current[key]

            if "/Parent" not in current:
                return default

            # Walk upward
            parent = current["/Parent"].get_object()
            if not isinstance(parent, DictionaryObject):
                # A malformed /Parent that does not resolve to a dictionary
                # terminates the inheritance walk (the key was not found).
                return default
            current = parent

    def __setitem__(self, key: Any, value: Any) -> Any:
        if not isinstance(key, PdfObject):
            raise ValueError("Key must be a PdfObject")
        if not isinstance(value, PdfObject):
            raise ValueError("Value must be a PdfObject")
        return dict.__setitem__(self, key, value)

    def setdefault(self, key: Any, value: Optional[Any] = None) -> Any:
        if not isinstance(key, PdfObject):
            raise ValueError("Key must be a PdfObject")
        if not isinstance(value, PdfObject):
            raise ValueError("Value must be a PdfObject")
        return dict.setdefault(self, key, value)

    def __getitem__(self, key: Any) -> PdfObject:
        return cast(PdfObject, dict.__getitem__(self, key).get_object())

    @property
    def xmp_metadata(self) -> Optional[XmpInformationProtocol]:
        """
        Retrieve XMP (Extensible Metadata Platform) data relevant to this
        object, if available.

        See Table 347 — Additional entries in a metadata stream dictionary.

        Returns:
          Returns a :class:`~pypdf.xmp.XmpInformation` instance
          that can be used to access XMP metadata from the document. Can also
          return None if no metadata was found on the document root.

        """
        from ..xmp import XmpInformation  # noqa: PLC0415

        metadata = self.get("/Metadata", None)
        if is_null_or_none(metadata):
            return None
        assert metadata is not None, "mypy"
        metadata = metadata.get_object()
        return XmpInformation(metadata)

    def write_to_stream(
        self, stream: StreamType, encryption_key: Union[str, bytes, None] = None
    ) -> None:
        if encryption_key is not None:  # deprecated
            deprecation_no_replacement(
                "the encryption_key parameter of write_to_stream", "5.0.0"
            )
        stream.write(b"<<\n")
        for key, value in self.items():
            if len(key) > 2 and key[1] == "%" and key[-1] == "%":
                continue
            key.write_to_stream(stream, encryption_key)
            stream.write(b" ")
            value.write_to_stream(stream)
            stream.write(b"\n")
        stream.write(b">>")

    @classmethod
    def _get_next_object_position(
            cls, position_before: int, position_end: int, generations: list[int], pdf: PdfReaderProtocol
    ) -> int:
        out = position_end
        for generation in generations:
            for x in pdf.xref[generation].values():
                if position_before < x <= position_end:
                    out = min(out, x)
        return out

    @classmethod
    def _read_unsized_from_stream(
            cls, *, stream: BinaryStreamType, pdf: PdfReaderProtocol, length: int,
    ) -> bytes:
        current_position = stream.tell()

        # Determine stream size.
        try:
            stream.seek(0, os.SEEK_END)
            stream_length = stream.tell()
        finally:
            stream.seek(current_position)

        object_position = cls._get_next_object_position(
            position_before=current_position, position_end=stream_length, generations=list(pdf.xref), pdf=pdf
        )

        bytes_to_read = object_position - current_position
        if bytes_to_read >= length:
            raise LimitReachedError(f"Requested length of {bytes_to_read} exceeds maximum allowed length.")

        # Read until the next object position.
        read_value = stream.read(bytes_to_read)
        endstream_position = read_value.find(b"endstream")
        if endstream_position < 0:
            raise PdfReadError(
                f"Unable to find 'endstream' marker for obj starting at {current_position}."
            )
        # 9 = len(b"endstream")
        stream.seek(current_position + endstream_position + 9)
        return read_value[: endstream_position - 1]

    @staticmethod
    def read_from_stream(
        stream: StreamType,
        pdf: Optional[PdfReaderProtocol],
        forced_encoding: Union[str, list[str], dict[int, str], None] = None,
        *,
        parsing_budget: Optional[StreamParsingBudget] = None,
    ) -> "DictionaryObject":
        tmp = stream.read(2)
        if tmp != b"<<":
            raise PdfReadError(
                f"Dictionary read error at byte {hex(stream.tell())}: "
                "stream must begin with '<<'"
            )
        data: dict[Any, Any] = {}
        remaining_count = get_configuration().dictionary_maximum_element_count
        while True:
            tok = read_non_whitespace(stream)
            if tok == b"%":
                stream.seek(-1, 1)
                skip_over_comment(stream)
                continue
            if not tok:
                raise PdfStrea…7543 tokens truncated…
            ignore_fields = []
        d__._clone(self, pdf_dest, force_duplicate, ignore_fields, visited)
        return d__

    def _clone(
        self,
        src: DictionaryObject,
        pdf_dest: PdfWriterProtocol,
        force_duplicate: bool,
        ignore_fields: Optional[Sequence[Union[str, int]]],
        visited: set[tuple[int, int]],
    ) -> None:
        """
        Update the object from src.

        Args:
            src:
            pdf_dest:
            force_duplicate:
            ignore_fields:

        """
        src_cs = cast("ContentStream", src)
        super().set_data(src_cs._data)
        self.pdf = pdf_dest
        self._operations = list(src_cs._operations)
        self.forced_encoding = src_cs.forced_encoding
        # no need to call DictionaryObjection or anything
        # like super(DictionaryObject,self)._clone(src, pdf_dest, force_duplicate, ignore_fields, visited)

    @staticmethod
    def _check_limits(
            *,
            remaining_elements: Optional[int] = None,
            parsing_budget: StreamParsingBudget,
            token_decrement: int
    ) -> Optional[int]:
        if remaining_elements is not None:
            remaining_elements -= 1
            if remaining_elements < 0:
                raise LimitReachedError("Reached maximum number of tokens.")
        parsing_budget.remaining_budget -= token_decrement
        if parsing_budget.remaining_budget < 0:
            raise LimitReachedError("Reached maximum number of tokens per stream.")
        return remaining_elements

    def _parse_content_stream(self, stream: StreamType) -> None:
        # 7.8.2 Content Streams
        stream.seek(0, 0)
        operands: list[Union[int, str, PdfObject]] = []
        parsing_budget = StreamParsingBudget(remaining_budget=get_configuration().stream_parsing_work_maximum_count)
        while True:
            peek = read_non_whitespace(stream)
            if peek in (b"", 0):
                break
            stream.seek(-1, 1)
            if peek.isalpha() or peek in (b"'", b'"'):
                operator = read_until_regex(
                    stream=stream, regex=NameObject.delimiter_pattern, length=self._OPERATOR_LENGTH_LIMIT
                )
                if operator == b"BI":
                    # begin inline image - a completely different parsing
                    # mechanism is required, of course... thanks buddy...
                    assert operands == []
                    self._check_limits(parsing_budget=parsing_budget, token_decrement=2)
                    ii = self._read_inline_image(stream, parsing_budget=parsing_budget)
                    self._operations.append((ii, b"INLINE IMAGE"))
                else:
                    self._check_limits(parsing_budget=parsing_budget, token_decrement=1)
                    self._operations.append((operands, operator))
                    operands = []
            elif peek == b"%":
                # If we encounter a comment in the content stream, we have to
                # handle it here. Typically, read_object will handle
                # encountering a comment -- but read_object assumes that
                # following the comment must be the object we're trying to
                # read. In this case, it could be an operator instead.
                while peek not in (b"\r", b"\n", b""):
                    peek = stream.read(1)
            else:
                self._check_limits(parsing_budget=parsing_budget, token_decrement=1)
                operands.append(read_object(stream, None, self.forced_encoding, parsing_budget=parsing_budget))

    def _read_inline_image(self, stream: StreamType, parsing_budget: StreamParsingBudget) -> dict[str, Any]:
        # begin reading just after the "BI" - begin image
        # first read the dictionary of settings.
        settings = DictionaryObject()
        remaining_count: Optional[int] = get_configuration().dictionary_maximum_element_count
        while True:
            tok = read_non_whitespace(stream)
            if not tok:
                raise PdfReadError("Unexpected end of stream.")
            stream.seek(-1, 1)
            if tok == b"I":
                # "ID" - begin of image data
                break
            remaining_count = self._check_limits(
                remaining_elements=remaining_count, parsing_budget=parsing_budget, token_decrement=2
            )

            key = read_object(stream, self.pdf, parsing_budget=parsing_budget)
            _ = read_non_whitespace(stream)
            stream.seek(-1, 1)
            value = read_object(stream, self.pdf, parsing_budget=parsing_budget)
            settings[key] = value
        # left at beginning of ID
        tmp = stream.read(3)
        assert tmp[:2] == b"ID"
        filtr = settings.get("/F", settings.get("/Filter", "not set"))
        savpos = stream.tell()
        if isinstance(filtr, list):
            filtr = filtr[0] if filtr else "not set"  # used forencoding
        if not isinstance(filtr, str):
            # A valid filter is a name or an array of names; anything else
            # cannot match the abbreviations below, so treat it as unfiltered.
            filtr = "not set"
        if "AHx" in filtr or "ASCIIHexDecode" in filtr:
            data = extract_inline__ascii_hex_decode(stream)
        elif "A85" in filtr or "ASCII85Decode" in filtr:
            data = extract_inline__ascii85_decode(stream)
        elif "RL" in filtr or "RunLengthDecode" in filtr:
            data = extract_inline__run_length_decode(stream)
        elif "DCT" in filtr or "DCTDecode" in filtr:
            data = extract_inline__dct_decode(stream)
        elif filtr == "not set":
            cs = settings.get("/CS", "")
            if isinstance(cs, list):
                cs = cs[0] if cs else ""
            if not isinstance(cs, str):
                cs = ""
            if "RGB" in cs:
                lcs: float = 3
            elif "CMYK" in cs:
                lcs = 4
            else:
                bits = settings.get(
                    "/BPC",
                    8 if cs in {"/I", "/G", "/Indexed", "/DeviceGray"} else -1,
                )
                if isinstance(bits, (int, float)) and bits > 0:
                    lcs = bits / 8.0
                else:
                    data = extract_inline_default(stream)
                    lcs = -1
            width = settings.get("/W")
            height = settings.get("/H")
            if lcs > 0 and isinstance(width, int) and isinstance(height, int):
                data = stream.read(ceil(width * lcs) * height)
            elif lcs > 0:
                # Without usable dimensions the raw sample length is unknown;
                # fall back to scanning for the `EI` marker.
                data = extract_inline_default(stream)
            # Move to the `EI` if possible.
            ei = read_non_whitespace(stream)
            stream.seek(-1, 1)
        else:
            data = extract_inline_default(stream)

        ei = stream.read(3)
        # An `EI` at the very end of the stream yields only two bytes; rewinding
        # unconditionally would step back into the marker (#3468).
        if len(ei) == 3:
            stream.seek(-1, 1)
        ei_trailing = ei[2:3]
        if ei[:2] != b"EI" or (ei_trailing != b"" and ei_trailing not in WHITESPACES):
            # Deal with wrong/missing `EI` tags. Example: Wrong dimensions specified above.
            stream.seek(savpos, 0)
            data = extract_inline_default(stream)
            ei = stream.read(3)
            if len(ei) == 3:
                stream.seek(-1, 1)
            ei_trailing = ei[2:3]
            if ei[:2] != b"EI" or (
                ei_trailing != b"" and ei_trailing not in WHITESPACES
            ):  # pragma: no cover
                # Check the same condition again. This should never fail as
                # edge cases are covered by `extract_inline_default` above,
                # but check this to make sure that we are behind the `EI` afterwards.
                raise PdfStreamError(
                    f"Could not extract inline image, even using fallback. Expected 'EI', got {ei!r}"
                )
        return {"settings": settings, "data": data}

    # This overrides the parent method
    def get_data(self) -> bytes:
        if not self._data:
            new_data = BytesIO()
            for operands, operator in self._operations:
                if operator == b"INLINE IMAGE":
                    new_data.write(b"BI")
                    dict_text = BytesIO()
                    operands["settings"].write_to_stream(dict_text)
                    new_data.write(dict_text.getvalue()[2:-2])
                    new_data.write(b"ID ")
                    new_data.write(operands["data"])
                    new_data.write(b"EI")
                else:
                    for op in operands:
                        op.write_to_stream(new_data)
                        new_data.write(b" ")
                    new_data.write(operator)
                new_data.write(b"\n")
            self._data = new_data.getvalue()
        return self._data

    # This overrides the parent method
    def set_data(self, data: bytes) -> None:
        super().set_data(data)
        self._operations = []

    @property
    def operations(self) -> list[tuple[Any, bytes]]:
        if not self._operations and self._data:
            self._parse_content_stream(BytesIO(self._data))
            self._data = b""
        return self._operations

    @operations.setter
    def operations(self, operations: list[tuple[Any, bytes]]) -> None:
        self._operations = operations
        self._data = b""

    def isolate_graphics_state(self) -> None:
        if self._operations:
            self._operations.insert(0, ([], b"q"))
            self._operations.append(([], b"Q"))
        elif self._data:
            self._data = b"q\n" + self._data + b"\nQ\n"

    # This overrides the parent method
    def write_to_stream(
        self, stream: StreamType, encryption_key: Union[str, bytes, None] = None
    ) -> None:
        if not self._data and self._operations:
            self.get_data()  # this ensures ._data is rebuilt
        super().write_to_stream(stream, encryption_key)


# Bound comment scanning without consuming Python recursion depth.
_MAX_LEADING_COMMENTS = 1000


def read_object(  # noqa: PLR0911
    stream: StreamType,
    pdf: Optional[PdfReaderProtocol],
    forced_encoding: Union[str, list[str], dict[int, str], None] = None,
    *,
    parsing_budget: Optional[StreamParsingBudget] = None,
) -> PdfObject:
    """
    Read the next object from the stream.

    Args:
        stream: The stream to read from.
        pdf: The corresponding PDF file.
        forced_encoding: The encoding to enforce, if any.
        parsing_budget: The allowed parsing budget, optional. If set, only applies to dictionaries,
            arrays and content streams.

    Returns:
        The parsed object.
    """
    tok = stream.read(1)
    stream.seek(-1, 1)  # reset to start
    if tok == b"%":
        # Skip consecutive comments in a loop instead of recursing per comment.
        skip_over_comments(stream, limit=_MAX_LEADING_COMMENTS)
        tok = stream.read(1)
        stream.seek(-1, 1)  # reset to start
    if tok == b"/":
        return NameObject.read_from_stream(stream, pdf)
    if tok == b"<":
        # hexadecimal string OR dictionary
        peek = stream.read(2)
        stream.seek(-2, 1)  # reset to start
        if peek == b"<<":
            return DictionaryObject.read_from_stream(stream, pdf, forced_encoding, parsing_budget=parsing_budget)
        return read_hex_string_from_stream(stream, forced_encoding)
    if tok == b"[":
        return ArrayObject.read_from_stream(stream, pdf, forced_encoding, parsing_budget=parsing_budget)
    if tok in (b"t", b"f"):
        return BooleanObject.read_from_stream(stream)
    if tok == b"(":
        return read_string_from_stream(stream, forced_encoding)
    if tok == b"e" and stream.read(6) == b"endobj":
        return NullObject()
    if tok == b"n":
        return NullObject.read_from_stream(stream)
    if tok in b"0123456789+-.":
        # number object OR indirect reference
        peek = stream.read(20)
        match = IndirectPattern.match(peek)
        if match is not None:
            assert pdf is not None, "mypy"
            # Continue after the "R", the match includes the character following it
            stream.seek(match.end() - 1 - len(peek), 1)
            # The object number includes an optional sign
            return IndirectObject(int(peek[: match.end(1)]), int(match[2]), pdf)
        number_end = NumberObject.NumberPattern.search(peek)
        if number_end is not None:
            # The whole number is in the peek, there is no need to read it again
            num = peek[: number_end.start()]
            stream.seek(len(num) - len(peek), 1)
            if b"." in num:
                return FloatObject(num)
            return NumberObject(num)
        stream.seek(-len(peek), 1)  # reset to start
        return NumberObject.read_from_stream(stream)
    pos = stream.tell()
    stream.seek(-20, 1)
    stream_extract = stream.read(80)
    stream.seek(pos)
    read_until_whitespace(stream)
    raise PdfReadError(
        f"Invalid Elementary Object starting with {tok!r} @{pos}: {stream_extract!r}"
    )


class Field(TreeObject):
    """
    A class representing a field dictionary.

    This class is accessed through
    :meth:`get_fields()<pypdf.PdfReader.get_fields>`
    """

    def __init__(self, data: DictionaryObject) -> None:
        DictionaryObject.__init__(self)
        field_attributes = (
            FieldDictionaryAttributes.attributes()
            + CheckboxRadioButtonAttributes.attributes()
        )
        self.indirect_reference = data.indirect_reference
        for attr in field_attributes:
            try:
                self[NameObject(attr)] = data[attr]
            except KeyError:
                pass
        if isinstance(self.get("/V"), EncodedStreamObject):
            d = cast(EncodedStreamObject, self[NameObject("/V")]).get_data()
            if isinstance(d, bytes):
                d_str = d.decode()
            elif d is None:
                d_str = ""
            else:
                raise Exception("Should never happen")
            self[NameObject("/V")] = TextStringObject(d_str)

    # TABLE 8.69 Entries common to all field dictionaries
    @property
    def field_type(self) -> Optional[NameObject]:
        """Read-only property accessing the type of this field."""
        return self.get(FieldDictionaryAttributes.FT)

    @property
    def parent(self) -> Optional[DictionaryObject]:
        """Read-only property accessing the parent of this field."""
        return self.get(FieldDictionaryAttributes.Parent)

    @property
    def kids(self) -> Optional["ArrayObject"]:
        """Read-only property accessing the kids of this field."""
        return self.get(FieldDictionaryAttributes.Kids)

    @property
    def name(self) -> Optional[str]:
        """Read-only property accessing the name of this field."""
        return self.get(FieldDictionaryAttributes.T)

    @property
    def alternate_name(self) -> Optional[str]:
        """Read-only property accessing the alternate name of this field."""
        return self.get(FieldDictionaryAttributes.TU)

    @property
    def mapping_name(self) -> Optional[str]:
        """
        Read-only property accessing the mapping name of this field.

        This name is used by pypdf as a key in the dictionary returned by
        :meth:`get_fields()<pypdf.PdfReader.get_fields>`
        """
        return self.get(FieldDictionaryAttributes.TM)

    @property
    def flags(self) -> Optional[int]:
        """
        Read-only property accessing the field flags, specifying various
        characteristics of the field (see Table 8.70 of the PDF 1.7 reference).
        """
        return self.get(FieldDictionaryAttributes.Ff)

    @property
    def value(self) -> Optional[Any]:
        """
        Read-only property accessing the value of this field.

        Format varies based on field type.
        """
        return self.get(FieldDictionaryAttributes.V)

    @property
    def default_value(self) -> Optional[Any]:
        """Read-only property accessing the default value of this field."""
        return self.get(FieldDictionaryAttributes.DV)

    @property
    def additional_actions(self) -> Optional[DictionaryObject]:
        """
        Read-only property accessing the additional actions dictionary.

        This dictionary defines the field's behavior in response to trigger
        events. See Section 8.5.2 of the PDF 1.7 reference.
        """
        return self.get(FieldDictionaryAttributes.AA)


class Destination(TreeObject):
    """
    A class representing a destination within a PDF file.

    See section 12.3.2 of the PDF 2.0 reference.

    Args:
        title: Title of this destination.
        page: Reference to the page of this destination. Should
            be an instance of :class:`IndirectObject<pypdf.generic.IndirectObject>`.
        fit: How the destination is displayed.

    Raises:
        PdfReadError: If destination type is invalid.

    """

    node: Optional[
        DictionaryObject
    ] = None  # node provide access to the original Object

    def remove_from_tree(self) -> None:
        """
        Remove the outline item this destination was built from.

        `reader.outline` and `writer.outline` yield detached copies rather than
        the nodes themselves, so the copy never has a `/Parent` and removing it
        would be a no-op. `node` is the dictionary in the document.
        """
        if self.node is None:
            super().remove_from_tree()
        elif "/Parent" not in self.node:
            raise ValueError("Removed child does not appear to be a tree item")
        else:
            TreeObject.remove_child(
                cast("TreeObject", self.node["/Parent"]), self.node
            )

    def __init__(
        self,
        title: Union[str, bytes],
        page: Union[NumberObject, IndirectObject, NullObject, DictionaryObject],
        fit: Fit,
    ) -> None:
        self._filtered_children: list[Any] = []  # used in PdfWriter

        typ = fit.fit_type
        args = fit.fit_args

        DictionaryObject.__init__(self)
        self[NameObject("/Title")] = TextStringObject(title)
        self[NameObject("/Page")] = page
        self[NameObject("/Type")] = typ

        # from table 8.2 of the PDF 1.7 reference.
        if typ == "/XYZ":
            if len(args) < 1:  # left is missing : should never occur
                args.append(NumberObject(0.0))
            if len(args) < 2:  # top is missing
                args.append(NumberObject(0.0))
            if len(args) < 3:  # zoom is missing
                args.append(NumberObject(0.0))
            # surplus arguments are ignored rather than failing the unpacking
            (
                self[NameObject(TA.LEFT)],
                self[NameObject(TA.TOP)],
                self[NameObject("/Zoom")],
            ) = args[:3]
        elif len(args) == 0:
            pass
        elif typ == TF.FIT_R:
            if len(args) == 4:  # a wrong number of arguments degrades to null
                (
                    self[NameObject(TA.LEFT)],
                    self[NameObject(TA.BOTTOM)],
                    self[NameObject(TA.RIGHT)],
                    self[NameObject(TA.TOP)],
                ) = args
            else:
                (
                    self[NameObject(TA.LEFT)],
                    self[NameObject(TA.BOTTOM)],
                    self[NameObject(TA.RIGHT)],
                    self[NameObject(TA.TOP)],
                ) = (NullObject(), NullObject(), NullObject(), NullObject())
        elif typ in [TF.FIT_H, TF.FIT_BH]:
            try:  # Prefer to be more robust not only to null parameters
                (self[NameObject(TA.TOP)],) = args
            except MemoryError:  # pragma: no cover  # TODO: BLE001
                raise
            except Exception:
                (self[NameObject(TA.TOP)],) = (NullObject(),)
        elif typ in [TF.FIT_V, TF.FIT_BV]:
            try:  # Prefer to be more robust not only to null parameters
                (self[NameObject(TA.LEFT)],) = args
            except MemoryError:  # pragma: no cover  # TODO: BLE001
                raise
            except Exception:
                (self[NameObject(TA.LEFT)],) = (NullObject(),)
        elif typ in [TF.FIT, TF.FIT_B]:
            pass
        else:
            raise PdfReadError(f"Unknown Destination Type: {typ!r}")

    @property
    def dest_array(self) -> "ArrayObject":
        return ArrayObject(
            [self.raw_get("/Page"), self["/Type"]]
            + [
                self[x]
                for x in ["/Left", "/Bottom", "/Right", "/Top", "/Zoom"]
                if x in self
            ]
        )

    def write_to_stream(
        self, stream: StreamType, encryption_key: Union[str, bytes, None] = None
    ) -> None:
        if encryption_key is not None:  # deprecated
            deprecation_no_replacement(
                "the encryption_key parameter of write_to_stream", "5.0.0"
            )
        stream.write(b"<<\n")
        key = NameObject("/D")
        key.write_to_stream(stream)
        stream.write(b" ")
        value = self.dest_array
        value.write_to_stream(stream)

        key = NameObject("/S")
        key.write_to_stream(stream)
        stream.write(b" ")
        value_s = NameObject("/GoTo")
        value_s.write_to_stream(stream)

        stream.write(b"\n")
        stream.write(b">>")

    @property
    def title(self) -> Optional[str]:
        """Read-only property accessing the destination title."""
        return self.get("/Title")

    @property
    def page(self) -> Optional[IndirectObject]:
        """Read-only property accessing the IndirectObject of the destination page."""
        return self.get("/Page")

    @property
    def typ(self) -> Optional[str]:
        """Read-only property accessing the destination type."""
        return self.get("/Type")

    @property
    def zoom(self) -> Optional[int]:
        """Read-only property accessing the zoom factor."""
        return self.get("/Zoom", None)

    @property
    def left(self) -> Optional[FloatObject]:
        """Read-only property accessing the left horizontal coordinate."""
        return self.get("/Left", None)

    @property
    def right(self) -> Optional[FloatObject]:
        """Read-only property accessing the right horizontal coordinate."""
        return self.get("/Right", None)

    @property
    def top(self) -> Optional[FloatObject]:
        """Read-only property accessing the top vertical coordinate."""
        return self.get("/Top", None)

    @property
    def bottom(self) -> Optional[FloatObject]:
        """Read-only property accessing the bottom vertical coordinate."""
        return self.get("/Bottom", None)

    @property
    def color(self) -> Optional["ArrayObject"]:
        """Read-only property accessing the color in (R, G, B) with values 0.0-1.0."""
        return cast(
            "ArrayObject",
            self.get("/C", ArrayObject([FloatObject(0), FloatObject(0), FloatObject(0)])),
        )

    @property
    def font_format(self) -> Optional[OutlineFontFlag]:
        """
        Read-only property accessing the font type.

        1=italic, 2=bold, 3=both
        """
        return OutlineFontFlag(self.get("/F", 0))

    @property
    def outline_count(self) -> Optional[int]:
        """
        Read-only property accessing the outline count.

        positive = expanded
        negative = collapsed
        absolute value = number of visible descendants at all levels
        """
        return self.get("/Count", None)
