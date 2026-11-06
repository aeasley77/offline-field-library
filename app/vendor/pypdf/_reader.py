Warning: truncated output (original token count: 19648)
Total output lines: 1833

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

import os
import re
import sys
from collections.abc import Iterable
from io import BytesIO, UnsupportedOperation
from operator import itemgetter
from pathlib import Path
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Union,
    cast,
)

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ._configuration import apply_legacy_configuration
from ._doc_common import PdfDocCommon, convert_to_int
from ._encryption import Encryption, PasswordType
from ._utils import (
    WHITESPACES_AS_BYTES,
    StrByteType,
    StreamType,
    get_stream_data,
    get_stream_size,
    logger_warning,
    read_non_whitespace,
    read_previous_line,
    read_until_whitespace,
    skip_over_comment,
    skip_over_whitespace,
)
from .constants import TrailerKeys as TK
from .errors import (
    EmptyFileError,
    FileNotDecryptedError,
    LimitReachedError,
    PdfReadError,
    PdfStreamError,
    WrongPasswordError,
)
from .generic import (
    ArrayObject,
    ByteStringObject,
    Destination,
    DictionaryObject,
    EncodedStreamObject,
    IndirectObject,
    NameObject,
    NullObject,
    NumberObject,
    PdfObject,
    StreamObject,
    TextStringObject,
    is_null_or_none,
    read_object,
)
from .xmp import XmpInformation

if TYPE_CHECKING:
    from ._page import PageObject


class PdfReader(PdfDocCommon):
    """
    Initialize a PdfReader object.

    This operation can take some time, as the PDF stream's cross-reference
    tables are read into memory.

    Args:
        stream: A File object or an object that supports the standard read
            and seek methods similar to a File object. Could also be a
            string representing a path to a PDF file.
        strict: Determines whether user should be warned of all
            problems and also causes some correctable problems to be fatal.
            Defaults to ``False``.
        password: Decrypt PDF file at initialization. If the
            password is None, the file will not be decrypted.
            Defaults to ``None``.
        root_object_recovery_limit: The maximum number of objects to query
            for recovering the Root object in non-strict mode. To disable
            this security measure, pass ``None``.
        xref_stream_maximum_entries: The maximum number of entries which are
            allowed inside a stream-based cross-reference stream.

    """

    xref: dict[int, dict[Any, Any]]
    trailer: DictionaryObject

    def __init__(
        self,
        stream: Union[StrByteType, Path],
        strict: bool = False,
        password: Union[str, bytes, None] = None,
        *,
        root_object_recovery_limit: Optional[int] = 10_000,
        xref_stream_maximum_entries: int = 2_000_000,
    ) -> None:
        self.strict = strict
        self.flattened_pages: Optional[list[PageObject]] = None

        #: Storage of parsed PDF objects.
        self.resolved_objects: dict[tuple[Any, Any], Optional[PdfObject]] = {}

        self._startxref: int = 0
        self.xref_index = 0
        self.xref = {}
        self.xref_free_entry: dict[int, dict[Any, Any]] = {}
        self.xref_objStm: dict[int, tuple[Any, Any]] = {}
        self.trailer = DictionaryObject()

        # Security parameters.
        self._root_object_recovery_limit = (
            root_object_recovery_limit if isinstance(root_object_recovery_limit, int) else sys.maxsize
        )
        self._xref_stream_maximum_entries = xref_stream_maximum_entries
        self._xref_stream_entry_count = 0
        apply_legacy_configuration()

        # Map page indirect_reference number to page number
        self._page_id2num: Optional[dict[Any, Any]] = None

        self._validated_root: Optional[DictionaryObject] = None

        self._initialize_stream(stream)
        self._known_objects: set[tuple[int, int]] = set()

        self._override_encryption = False
        self._encryption: Optional[Encryption] = None
        if self.is_encrypted:
            self._handle_encryption(password)
        elif password is not None:
            raise PdfReadError("Not an encrypted file")

        self._named_destinations_cache: Optional[dict[str, Destination]] = None
        self._object_stream_resolution_stack: list[int] = []

    def _initialize_stream(self, stream: Union[StrByteType, Path]) -> None:
        if hasattr(stream, "mode") and "b" not in stream.mode:
            logger_warning(
                "PdfReader stream/file object is not in binary mode. "
                "It may not be read correctly.",
                source=__name__,
            )
        self._stream_opened = False
        if isinstance(stream, (str, Path)):
            with open(stream, "rb") as fh:
                stream = BytesIO(fh.read())
            self._stream_opened = True
        self.read(stream)
        self.stream = stream

    def _handle_encryption(self, password: Optional[Union[str, bytes]]) -> None:
        self._override_encryption = True
        # Some documents may not have a /ID, use two empty
        # byte strings instead. Solves
        # https://github.com/py-pdf/pypdf/issues/608
        id_entry = self.trailer.get(TK.ID, NullObject()).get_object()
        id1_entry = b""
        if isinstance(id_entry, ArrayObject) and id_entry:
            first_id_entry = id_entry[0].get_object()
            if isinstance(first_id_entry, (ByteStringObject, TextStringObject)):
                id1_entry = first_id_entry.original_bytes
            else:
                logger_warning("Ignoring non-string first /ID entry of the trailer", source=__name__)
        elif not isinstance(id_entry, NullObject):
            logger_warning("Ignoring malformed /ID entry of the trailer", source=__name__)
        encrypt_entry = self.trailer[TK.ENCRYPT]
        if not isinstance(encrypt_entry, DictionaryObject):
            raise PdfReadError("/Encrypt entry of the trailer is not a dictionary")
        self._encryption = Encryption.read(encrypt_entry, id1_entry)

        # try empty password if no password provided
        pwd = password if password is not None else b""
        if (
            self._encryption.verify(pwd, strict=self.strict) == PasswordType.NOT_DECRYPTED
            and password is not None
        ):
            # raise if password provided
            raise WrongPasswordError("Wrong password")
        self._override_encryption = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the stream if opened in __init__ and clear memory."""
        if self._stream_opened:
            self.stream.close()
        self.flattened_pages = []
        self.resolved_objects = {}
        self.trailer = DictionaryObject()
        self.xref = {}
        self.xref_free_entry = {}
        self.xref_objStm = {}

    @property
    def root_object(self) -> DictionaryObject:
        """Provide access to "/Root". Standardized with PdfWriter."""
        if self._validated_root:
            return self._validated_root
        root = self.trailer.get(TK.ROOT, NullObject()).get_object()
        root_dictionary: DictionaryObject
        if isinstance(root, DictionaryObject):
            root_dictionary = root
        else:
            # The catalog has to be a dictionary. Anything else cannot be used,
            # thus treat it like an empty one and attempt the recovery below.
            root_dictionary = DictionaryObject()
        if is_null_or_none(root):
            logger_warning('Cannot find "/Root" key in trailer', source=__name__)
        elif root_dictionary.get("/Type") == "/Catalog":
            self._validated_root = root_dictionary
        else:
            logger_warning("Invalid Root object in trailer", source=__name__)
        if self._validated_root is None:
            logger_warning('Searching object with "/Catalog" key', source=__name__)
            number_of_objects = cast(int, self.trailer.get("/Size", 0))
            for i in range(number_of_objects):
                if i >= self._root_object_recovery_limit:
                    raise LimitReachedError("Maximum Root object recovery limit reached.")
                try:
                    obj = self.get_object(i + 1)
                except MemoryError:  # pragma: no cover  # TODO: BLE001
                    raise
                except Exception:  # to be sure to capture all errors
                    obj = None
                if isinstance(obj, DictionaryObject) and obj.get("/Type") == "/Catalog":
                    self._validated_root = obj
                    logger_warning(
                        "Root found at %(obj_reference)r",
                        source=__name__,
                        obj_reference=obj.indirect_reference,
                    )
                    break
        if self._validated_root is None:
            if "/Pages" in root_dictionary:
                logger_warning(
                    "Possible root found at %(root_ref)r, but missing /Catalog key",
                    source=__name__,
                    root_ref=root_dictionary.indirect_reference,
                )
                self._validated_root = root_dictionary
            else:
                raise PdfReadError("Cannot find Root object in pdf")
        return self._validated_root

    @property
    def _info(self) -> Optional[DictionaryObject]:
        """
        Provide access to "/Info". Standardized with PdfWriter.

        Returns:
            /Info Dictionary; None if the entry does not exist

        """
        info = self.trailer.get(TK.INFO, None)
        if is_null_or_none(info):
            return None
        assert info is not None, "mypy"
        info = info.get_object()
        if not isinstance(info, DictionaryObject):
            raise PdfReadError(
                "Trailer not found or does not point to a document information dictionary"
            )
        return info

    @property
    def _ID(self) -> Optional[ArrayObject]:
        """
        Provide access to "/ID". Standardized with PdfWriter.

        Returns:
            /ID array; None if the entry does not exist

        """
        file_identifiers = self.trailer.get(TK.ID, None)
        if is_null_or_none(file_identifiers):
            return None
        assert file_identifiers is not None, "mypy"
        return cast(ArrayObject, file_identifiers.get_object())

    @property
    def pdf_header(self) -> str:
        """
        The first 8 bytes of the file.

        This is typically something like ``'%PDF-1.6'`` and can be used to
        detect if the file is actually a PDF file and which version it is.
        """
        # TODO: Make this return a bytes object for consistency
        #       but that needs a deprecation
        loc = self.stream.tell()
        self.stream.seek(0, 0)
        pdf_file_version = self.stream.read(8).decode("utf-8", "backslashreplace")
        self.stream.seek(loc, 0)  # return to where it was
        return pdf_file_version

    @property
    def xmp_metadata(self) -> Optional[XmpInformation]:
        """XMP (Extensible Metadata Platform) data."""
        try:
            # The document-level metadata stream is exempt from encryption
            # only if /EncryptMetadata is false (ISO 32000-2, Table 21).
            self._override_encryption = (
                self._encryption is not None and not self._encryption.EncryptMetadata
            )
            return cast(XmpInformation, self.root_object.xmp_metadata)
        finally:
            self._override_encryption = False

    def _get_page_number_by_indirect(
        self, indirect_reference: Union[int, NullObject, IndirectObject, None]
    ) -> Optional[int]:
        """
        Retrieve the page number from an indirect reference.

        Args:
            indirect_reference: The indirect reference to locate.

        Returns:
            Page number or None.

        """
        if self._page_id2num is None:
            self._page_id2num = {
                x.indirect_reference.idnum: i for i, x in enumerate(self.pages)  # type: ignore[union-attr]
            }

        if is_null_or_none(indirect_reference):
            return None
        assert isinstance(indirect_reference, (int, IndirectObject)), "mypy"
        if isinstance(indirect_reference, int):
            idnum = indirect_reference
        else:
            idnum = indirect_reference.idnum
        assert self._page_id2num is not None, "hint for mypy"
        return self._page_id2num.get(idnum, None)

    def _get_object_from_stream(
        self, indirect_reference: IndirectObject
    ) -> PdfObject:
        obj_id = indirect_reference.idnum
        if obj_id in self._object_stream_resolution_stack:
            start = self._object_stream_resolution_stack.index(obj_id)
            cycle = [*self._object_stream_resolution_stack[start:], obj_id]
            raise PdfReadError(
                "Circular object-stream reference detected: " + " -> ".join(map(str, cycle))
            )
        self._object_stream_resolution_stack.append(obj_id)

        try:
            # indirect reference to object in object stream
            # read the entire object stream into memory
            stmnum, _idx = self.xref_objStm[indirect_reference.idnum]
            obj_stm: EncodedStreamObject = IndirectObject(stmnum, 0, self).get_object()  # type: ignore[assignment]
            # This is an xref to a stream, so its type better be a stream
            assert cast(str, obj_stm["/Type"]) == "/ObjStm"
            # Parse ALL objects in this stream in one pass and cache them.
            # This avoids O(N²) behavior when many objects from the same stream
            # are resolved individually (each call would re-parse the header).
            stream_data = BytesIO(obj_stm.get_data())
            n_value = obj_stm.get("/N")
            first_value = obj_stm.get("/First")
            if not isinstance(n_value, NumberObject) or not isinstance(
                first_value, NumberObject
            ):
                raise PdfReadError(
                    f"Invalid /ObjStm header for object {stmnum}: "
                    "/N or /First missing or not a number"
                )
            n = int(n_value)
            first_offset = int(first_value)

            stream_length = get_stream_size(stream_data)
            if n < 0 or not 0 <= first_offset <= stream_length:
                # A negative /N, or a /First outside the stream, cannot
                # describe a valid object stream; treating it as empty
                # avoids leaking a ValueError/OverflowError from a bad seek.
                if self.strict:
                    raise PdfReadError(
                        f"Invalid /N ({n}) or /First ({first_offset}) in object stream {stmnum}."
                    )
                logger_warning(
                    (
                        "Invalid /N (%(n)d) or /First (%(first)d) in object stream "
                        "%(stmnum)d; ignoring the stream."
                    ),
                    source=__name__,
                    n=n,
                    first=first_offset,
                    stmnum=stmnum,
                )
                return NullObject()

            # ObjStm header format: "objnum offset objnum offset ..."
            # smallest possible entry: "0 0" = 3 bytes (1 digit + 1 space + 1 digit)
            # using // 4 would reject a valid 3-byte single entry (3 // 4 = 0)
            max_n = stream_length // 3
            stream_data.seek(0)
            if n > max_n:
                if self.strict:
                    raise LimitReachedError(f"Value /N {n} for object {stmnum} exceeds maximum allowed value {max_n}.")
                logger_warning(
                    (
                        "Value /N %(n)d for object %(stmnum)d exceeds maximum allowed value %(max_n)d. "
                        "Limiting to %(max_n)d."
                    ),
                    source=__name__,
                    n=n,
                    stmnum=stmnum,
                    max_n=max_n,
                )
                n = max_n

            # Phase 1: Read the index (objnum, offset) pairs from the header.
            obj_index: list[tuple[int, int]] = []
            for _i in range(n):
                read_non_whitespace(stream_data)
                stream_data.seek(-1, 1)
                objnum = NumberObject.read_from_stream(stream_data)
                read_non_whitespace(stream_data)
                stream_data.seek(-1, 1)
                offset = NumberObject.read_from_stream(stream_data)
                read_non_whitespace(stream_data)
                stream_data.seek(-1, 1)
                if objnum < 0 or offset < 0 or first_offset + offset > stream_length:
                    # An object number or target position outside the stream
                    # cannot be valid; skipping the entry avoids leaking a
                    # ValueError/OverflowError from a bad seek while keeping
                    # the other entries.
                    if self.strict:
                        raise PdfReadError(
                            f"Invalid object number ({objnum}) or offset ({offset}) "
                            f"in object stream {stmnum}."
                        )
                    logger_warning(
                        (
                            "Invalid object number (%(objnum)d) or offset (%(offset)d) "
                            "in object stream %(stmnum)d; skipping the entry."
                        ),
                        source=__name__,
                        objnum=objnum,
                        offset=offset,
                        stmnum=stmnum,
                    )
                    continue
                obj_index.append((int(objnum), int(offset)))

            # Phase 2: Parse each object and cache it.
            target_obj: PdfObject = NullObject()
            found = False
            for i, (obj_num, obj_offset) in enumerate(obj_index):
                # Skip objects already in the cache.
                cached = self.cache_get_indirect_object(0, obj_num)
                if cached is not None:
                    if obj_num == indirect_reference.idnum:
                        target_obj = cached
                        found = True
                    continue

                stream_data.seek(first_offset + obj_offset, 0)

                # To cope with case where the 'pointer' is on a white space
                read_non_whitespace(stream_data)
                stream_data.seek(-1, 1)

                try:
                    obj = read_object(stream_data, self)
                except PdfStreamError as exc:
                    # Stream object cannot be read. Normally, a critical error, but
                    # Adobe Reader doesn't complain, so continue (in strict mode?)
                    logger_warning(
                        "Invalid stream (index %(index)d) within object %(obj_num)d 0: %(exc)s",
                        source=__name__,
                        index=i,
                        obj_num=obj_num,
                        exc=exc,
                    )
                    if self.strict:  # pragma: no cover
                        raise PdfReadError(
                            f"Cannot read object stream: {exc}"
                        ) from exc  # pragma: no cover
                    obj = NullObject()  # pragma: no cover

                # Only cache if this stream is the authoritative source for the object.
                # Incremental updates may override objects originally in the stream;
                # caching those stale versions would shadow the newer xref entry.
                authoritative_stm, _idx = self.xref_objStm.get(obj_num, (None, None))
                if authoritative_stm == stmnum:
                    self.cache_indirect_object(0, obj_num, obj)

                if obj_num == indirect_reference.idnum:
                    target_obj = obj
                    found = True

            if not found and self.strict:  # pragma: no cover
                raise PdfReadError(
                    "This is a fatal error in strict mode."
                )  # pragma: no cover
            return target_obj
        finally:
            self._object_stream_resolution_stack.pop()

    def get_object(
        self, indirect_reference: Union[int, IndirectObject]
    ) -> Optional[PdfObject]:
        if isinstance(indirect_reference, int):
            indirect_reference = IndirectObject(indirect_reference, 0, self)

        retval = self.cache_get_indirect_object(
            indirect_reference.generation, indirect_reference.idnum
        )
        key = (
            indirect_reference.generation,
            indirect_reference.idnum,
        )
        if key in self.resolved_objects:
            return retval

        if (
            indirect_reference.generation == 0
            and indirect_reference.idnum in self.xref_objStm
        ):
            retval = self._get_object_from_stream(indirect_reference)
        elif (
            indirect_reference.generation in self.xref
            and indirect_reference.idnum in self.xref[indirect_reference.generation]
        ):
            if self.xref_free_entry.get(indirect_reference.generation, {}).get(
                indirect_reference.idnum, False
            ):
                return NullObject()
            start = self.xref[indirect_reference.generation][indirect_reference.idnum]
            self.stream.seek(start, 0)
            try:
                idnum, generation = self.read_object_header(self.stream)
                if (
                    idnum != indirect_reference.idnum
                    or generation != indirect_reference.generation
                ):
                    raise PdfReadError("Not matching, we parse the file for it")
            except MemoryError:  # pragma: no cover  # TODO: BLE001
                raise
            except Exception:
                buf = get_stream_data(self.stream)
                m = re.search(
                    rf"\s{indirect_reference.idnum}\s+{indirect_reference.generation}\s+obj".encode(),…7648 tokens truncated…        self.trailer[NameObject(key)] = xrefstream.raw_get(key)
        if "/XRefStm" in xrefstream:
            p = self.stream.tell()
            self.stream.seek(cast(int, xrefstream["/XRefStm"]) + 1, 0)
            self._read_pdf15_xref_stream(self.stream)
            self.stream.seek(p, 0)

    def _read_xref(self, stream: StreamType) -> Optional[int]:
        self._read_standard_xref_table(stream)
        if stream.read(1) == b"":
            return None
        stream.seek(-1, 1)
        read_non_whitespace(stream)
        stream.seek(-1, 1)
        new_trailer = cast(dict[str, Any], read_object(stream, self))
        for key, value in new_trailer.items():
            if key not in self.trailer:
                self.trailer[key] = value
        if "/XRefStm" in new_trailer:
            p = stream.tell()
            stream.seek(cast(int, new_trailer["/XRefStm"]) + 1, 0)
            try:
                self._read_pdf15_xref_stream(stream)
            except MemoryError:  # pragma: no cover  # TODO: BLE001
                raise
            except Exception:
                logger_warning(
                    "XRef object at %(xref_stm)d can not be read, some object may be missing",
                    source=__name__,
                    xref_stm=int(new_trailer["/XRefStm"]),
                )
            stream.seek(p, 0)
        if "/Prev" in new_trailer:
            return cast(int, new_trailer["/Prev"])
        return None

    def _read_xref_other_error(
        self, stream: StreamType, startxref: int
    ) -> Optional[int]:
        # some PDFs have /Prev=0 in the trailer, instead of no /Prev
        if startxref == 0:
            if self.strict:
                raise PdfReadError(
                    "/Prev=0 in the trailer (try opening with strict=False)"
                )
            logger_warning(
                "/Prev=0 in the trailer - assuming there is no previous xref table",
                source=__name__,
            )
            return None
        # bad xref character at startxref. Let's see if we can find
        # the xref table nearby, as we've observed this error with an
        # off-by-one before.
        stream.seek(-11, 1)
        tmp = stream.read(20)
        xref_loc = tmp.find(b"xref")
        if xref_loc != -1:
            startxref -= 10 - xref_loc
            return startxref
        # No explicit xref table, try finding a cross-reference stream.
        stream.seek(startxref, 0)
        for look in range(25):  # value extended to cope with more linearized files
            if stream.read(1).isdigit():
                # This is not a standard PDF, consider adding a warning
                startxref += look
                return startxref
        # no xref table found at specified location
        if "/Root" in self.trailer and not self.strict:
            # if Root has been already found, just raise warning
            logger_warning("Invalid parent xref., rebuild xref", source=__name__)
            try:
                self._rebuild_xref_table(stream)
            except Exception as exception:  # pragma: no cover
                raise PdfReadError("Cannot rebuild xref") from exception  # pragma: no cover
            return None
        raise PdfReadError("Could not find xref table at specified location")

    def _sanitize_pdf15_xref_stream_index_pairs(
            self, index_pairs: list[int], entry_sizes: list[int], xref_stream: StreamObject
    ) -> list[int]:
        # `entry_sizes` holds the byte widths for the entries. Summing determines the total number of bytes per entry.
        # We expect up to 3 values. `min_entry_bytes` will be the smallest plausible size of one xref entry.
        min_entry_bytes = sum(int(entry_sizes[i]) for i in range(min(len(entry_sizes), 3)))
        if min_entry_bytes == 0:
            message = "Cross-reference stream encodes no entry data."
            if self.strict:
                raise PdfStreamError(message)
            logger_warning(message, source=__name__)
            return []

        # maximum number of entries that could physically fit
        max_entries = len(xref_stream.get_data()) // min_entry_bytes + 1

        result = []
        total = 0

        for index, pair_value in enumerate(index_pairs):
            pair_value_int = int(pair_value)

            # `index_pairs` has the format `[start0, count0, start1, count1, ...]`
            # Only modify the counts here, but keep the start values.
            if index % 2 == 1:
                if pair_value_int < 0:
                    if self.strict:
                        raise PdfStreamError(f"Negative XRef count {pair_value_int}.")
                    logger_warning(
                        "Negative XRef count %(count)d, using 0.",
                        source=__name__,
                        count=pair_value_int,
                    )
                    pair_value_int = 0

                if total + pair_value_int > max_entries:
                    if self.strict:
                        raise LimitReachedError(
                            f"Total XRef entries {total + pair_value_int} exceed maximum allowed value {max_entries}."
                        )
                    new_v = max(0, max_entries - total)
                    logger_warning(
                        "Clamping XRef count from %(old_count)d to %(new_count)d to fit stream size.",
                        source=__name__,
                        old_count=pair_value_int,
                        new_count=new_v,
                    )
                    pair_value_int = new_v

                total += pair_value_int

            result.append(pair_value_int)

        return result

    def _read_pdf15_xref_stream(self, stream: StreamType) -> StreamObject:
        """Read the cross-reference stream for PDF 1.5+."""
        stream.seek(-1, 1)
        stream_idnum, stream_generation = self.read_object_header(stream)
        xref_stream = cast(StreamObject, read_object(stream, self))
        if cast(str, xref_stream["/Type"]) != "/XRef":
            raise PdfReadError(f"Unexpected type {xref_stream['/Type']!r}")
        self.cache_indirect_object(stream_generation, stream_idnum, xref_stream)

        # Index pairs specify the subsections in the dictionary.
        # If none, create one subsection that spans everything.
        if "/Size" not in xref_stream:
            # According to table 17 of the PDF 2.0 specification, this key is required.
            raise PdfReadError(f"Size missing from XRef stream {xref_stream!r}!")
        index_pairs = xref_stream.get("/Index", [0, xref_stream["/Size"]])

        entry_sizes = cast(list[int], xref_stream.get("/W"))
        assert len(entry_sizes) >= 3
        if self.strict and len(entry_sizes) > 3:
            raise PdfReadError(f"Too many entry sizes: {entry_sizes}")
        index_pairs = self._sanitize_pdf15_xref_stream_index_pairs(
            index_pairs=index_pairs, entry_sizes=entry_sizes, xref_stream=xref_stream
        )

        self._xref_stream_entry_count += sum(index_pairs[1::2])
        if self._xref_stream_entry_count > self._xref_stream_maximum_entries:
            raise LimitReachedError(
                f"Maximum XRef stream entry limit reached: "
                f"{self._xref_stream_entry_count} > {self._xref_stream_maximum_entries}."
            )

        stream_data = BytesIO(xref_stream.get_data())

        def get_entry(i: int) -> Union[int, tuple[int, ...]]:
            # Reads the correct number of bytes for each entry. See the
            # discussion of the W parameter in PDF spec table 17.
            if entry_sizes[i] > 0:
                d = stream_data.read(entry_sizes[i])
                return convert_to_int(d, entry_sizes[i])

            # PDF Spec Table 17: A value of zero for an element in the
            # W array indicates...the default value shall be used
            if i == 0:
                return 1  # First value defaults to 1
            return 0

        def used_before(num: int, generation: Union[int, tuple[int, ...]]) -> bool:
            # We move backwards through the xrefs, don't replace any.
            return num in self.xref.get(generation, []) or num in self.xref_objStm  # type: ignore[arg-type]

        # Iterate through each subsection
        self._read_xref_subsections(index_pairs, get_entry, used_before)
        return xref_stream

    @staticmethod
    def _get_xref_issues(stream: StreamType, startxref: int) -> int:
        """
        Return an int which indicates an issue. 0 means there is no issue.

        Args:
            stream:
            startxref:

        Returns:
            0 means no issue, other values represent specific issues.

        """
        if startxref == 0:
            return 4

        stream.seek(startxref - 1, 0)  # -1 to check character before
        line = stream.read(1)
        if line == b"j":
            line = stream.read(1)
        if line not in b"\r\n \t":
            return 1
        line = stream.read(4)
        if line != b"xref":
            # not a xref so check if it is an XREF object
            line = b""
            while line in b"0123456789 \t":
                line = stream.read(1)
                if line == b"":
                    return 2
            line += stream.read(2)  # 1 char already read, +2 to check "obj"
            if line.lower() != b"obj":
                return 3
        return 0

    @classmethod
    def _find_pdf_objects(cls, data: bytes) -> Iterable[tuple[int, int, int]]:
        index = 0
        ord_0 = ord("0")
        ord_9 = ord("9")
        while True:
            index = data.find(b" obj", index)
            if index == -1:
                return

            index_before_space = index - 1

            # Skip whitespace backwards
            while index_before_space >= 0 and data[index_before_space] in WHITESPACES_AS_BYTES:
                index_before_space -= 1

            # Read generation number
            generation_end = index_before_space + 1
            while index_before_space >= 0 and ord_0 <= data[index_before_space] <= ord_9:
                index_before_space -= 1
            generation_start = index_before_space + 1

            # Skip whitespace
            while index_before_space >= 0 and data[index_before_space] in WHITESPACES_AS_BYTES:
                index_before_space -= 1

            # Read object number
            object_end = index_before_space + 1
            while index_before_space >= 0 and ord_0 <= data[index_before_space] <= ord_9:
                index_before_space -= 1
            object_start = index_before_space + 1

            # Validate
            if object_start < object_end and generation_start < generation_end:
                object_number = int(data[object_start:object_end])
                generation_number = int(data[generation_start:generation_end])

                yield object_number, generation_number, object_start

            index += 4  # len(b" obj")

    @classmethod
    def _find_pdf_trailers(cls, data: bytes) -> Iterable[int]:
        index = 0
        data_length = len(data)
        while True:
            index = data.find(b"trailer", index)
            if index == -1:
                return

            index_after_trailer = index + 7  # len(b"trailer")

            # Skip whitespace
            while index_after_trailer < data_length and data[index_after_trailer] in WHITESPACES_AS_BYTES:
                index_after_trailer += 1

            # Must be dictionary start
            if index_after_trailer + 1 < data_length and data[index_after_trailer:index_after_trailer+2] == b"<<":
                yield index_after_trailer  # offset of '<<'

            index += 7  # len(b"trailer")

    def _rebuild_xref_table(self, stream: StreamType) -> None:
        self.xref = {}
        stream.seek(0, 0)
        stream_data = stream.read(-1)

        for object_number, generation_number, object_start in self._find_pdf_objects(stream_data):
            if generation_number not in self.xref:
                self.xref[generation_number] = {}
            self.xref[generation_number][object_number] = object_start

        logger_warning("parsing for Object Streams", source=__name__)
        # PDF 1.5+ files may carry the trailer keys inside a cross-reference
        # stream instead of behind a `trailer` keyword. Collect them here,
        # keyed by their offset, to merge them below in file order.
        xref_stream_trailers: list[tuple[int, DictionaryObject]] = []
        for generation_number in self.xref:
            for object_number in self.xref[generation_number]:
                # get_object in manual
                object_start = self.xref[generation_number][object_number]
                stream.seek(object_start, 0)
                try:
                    _ = self.read_object_header(stream)
                    obj = cast(StreamObject, read_object(stream, self))
                    object_type = obj.get("/Type", "")
                    if object_type == "/XRef":
                        trailer = DictionaryObject()
                        for key in self._XREF_STREAM_TRAILER_KEYS:
                            if key in obj:
                                trailer[NameObject(key)] = obj.raw_get(key)
                        xref_stream_trailers.append((object_start, trailer))
                        continue
                    if object_type != "/ObjStm":
                        continue
                    object_stream = BytesIO(obj.get_data())
                    actual_count = 0
                    while True:
                        current = read_until_whitespace(
                            object_stream, max_bytes=IndirectObject._MAXIMUM_PART_LENGTH, strict=self.strict
                        )
                        if not current.isdigit():
                            break
                        inner_object_number = int(current)
                        skip_over_whitespace(object_stream)
                        object_stream.seek(-1, 1)
                        current = read_until_whitespace(
                            object_stream, max_bytes=IndirectObject._MAXIMUM_PART_LENGTH, strict=self.strict
                        )
                        if not current.isdigit():  # pragma: no cover
                            break  # pragma: no cover
                        inner_offset = int(current)
                        self.xref_objStm[inner_object_number] = (object_number, inner_offset)
                        actual_count += 1
                    expected_count = cast(int, obj["/N"])
                    if actual_count != expected_count:  # pragma: no cover
                        logger_warning(  # pragma: no cover
                            (
                                "found %(actual_count)d objects within "
                                "Object(%(object_number)d,%(generation_number)d) "
                                "whereas %(expected)d expected"
                            ),
                            source=__name__,
                            actual_count=actual_count,
                            object_number=object_number,
                            generation_number=generation_number,
                            expected=expected_count,
                        )
                except LimitReachedError:
                    # Do not let the broad recovery below bypass the token-length limit
                    # when strict parsing is enabled.
                    raise
                except MemoryError:  # pragma: no cover  # TODO: BLE001
                    raise
                except Exception:  # could be multiple causes
                    pass

        stream.seek(0, 0)
        trailers: list[tuple[int, dict[Any, Any]]] = list(xref_stream_trailers)
        for position in self._find_pdf_trailers(stream_data):
            stream.seek(position, 0)
            trailers.append((position, cast(dict[Any, Any], read_object(stream, self))))
        # Here, we are parsing the file from start to end, the new data have to erase the existing.
        for _, new_trailer in sorted(trailers, key=itemgetter(0)):
            for key, value in new_trailer.items():
                self.trailer[key] = value

    def _read_xref_subsections(
        self,
        idx_pairs: list[int],
        get_entry: Callable[[int], Union[int, tuple[int, ...]]],
        used_before: Callable[[int, Union[int, tuple[int, ...]]], bool],
    ) -> None:
        """Read and process the subsections of the xref."""
        for start, size in self._pairs(idx_pairs):
            # The subsections must increase
            for num in range(start, start + size):
                # The first entry is the type
                xref_type = get_entry(0)
                # The rest of the elements depend on the xref_type
                if xref_type == 0:
                    # linked list of free objects
                    next_free_object = get_entry(1)  # noqa: F841
                    next_generation = get_entry(2)  # noqa: F841
                elif xref_type == 1:
                    # objects that are in use but are not compressed
                    byte_offset = get_entry(1)
                    generation = get_entry(2)
                    if generation not in self.xref:
                        self.xref[generation] = {}  # type: ignore[index]
                    if not used_before(num, generation):
                        self.xref[generation][num] = byte_offset  # type: ignore[index]
                elif xref_type == 2:
                    # compressed objects
                    objstr_num = get_entry(1)
                    obstr_idx = get_entry(2)
                    generation = 0  # PDF spec table 18, generation is 0
                    if not used_before(num, generation):
                        self.xref_objStm[num] = (objstr_num, obstr_idx)
                elif self.strict:
                    raise PdfReadError(f"Unknown xref type: {xref_type}")

    def _pairs(self, array: list[int]) -> Iterable[tuple[int, int]]:
        """Iterate over pairs in the array."""
        i = 0
        while i + 1 < len(array):
            yield array[i], array[i + 1]
            i += 2

    def decrypt(self, password: Union[str, bytes]) -> PasswordType:
        """
        When using an encrypted / secured PDF file with the PDF Standard
        encryption handler, this function will allow the file to be decrypted.
        It checks the given password against the document's user password and
        owner password, and then stores the resulting decryption key if either
        password is correct.

        It does not matter which password was matched. Both passwords provide
        the correct decryption key that will allow the document to be used with
        this library.

        Args:
            password: The password to match.

        Returns:
            An indicator if the document was decrypted and whether it was the
            owner password or the user password.

        """
        if not self._encryption:
            raise PdfReadError("Not encrypted file")
        # TODO: raise Exception for wrong password
        return self._encryption.verify(password, strict=self.strict)

    @property
    def is_encrypted(self) -> bool:
        """
        Read-only boolean property showing whether this PDF file is encrypted.

        Note that this property, if true, will remain true even after the
        :meth:`decrypt()<pypdf.PdfReader.decrypt>` method is called.
        """
        return TK.ENCRYPT in self.trailer

    def add_form_topname(self, name: str) -> Optional[DictionaryObject]:
        """
        Add a top level form that groups all form fields below it.

        Args:
            name: text string of the "/T" Attribute of the created object

        Returns:
            The created object. ``None`` means no object was created.

        """
        catalog = self.root_object

        if "/AcroForm" not in catalog or not isinstance(
            catalog["/AcroForm"], DictionaryObject
        ):
            return None
        acroform = cast(DictionaryObject, catalog[NameObject("/AcroForm")])
        if "/Fields" not in acroform:
            # TODO: No error but this may be extended for XFA Forms
            return None

        interim = DictionaryObject()
        interim[NameObject("/T")] = TextStringObject(name)
        interim[NameObject("/Kids")] = acroform[NameObject("/Fields")]
        # Allocate the new object_id beyond the source-file range and all cached object IDs.
        object_id = max(
            cast(int, self.trailer.get("/Size", 0)) - 1,
            max((i for entries in self.xref.values() for i in entries), default=0),
            max(self.xref_objStm, default=0),
            max((i for _, i in self.resolved_objects), default=0),
        ) + 1
        self.cache_indirect_object(0, object_id, interim)
        arr = ArrayObject()
        arr.append(interim.indirect_reference)
        acroform[NameObject("/Fields")] = arr
        for o in cast(ArrayObject, interim["/Kids"]):
            obj = o.get_object()
            if "/Parent" in obj:
                logger_warning(
                    "Top Level Form Field %(obj_ref)s has a non-expected parent",
                    source=__name__,
                    obj_ref=obj.indirect_reference,
                )
            obj[NameObject("/Parent")] = interim.indirect_reference
        return interim

    def rename_form_topname(self, name: str) -> Optional[DictionaryObject]:
        """
        Rename top level form field that all form fields below it.

        Args:
            name: text string of the "/T" field of the created object

        Returns:
            The modified object. ``None`` means no object was modified.

        """
        catalog = self.root_object

        if "/AcroForm" not in catalog or not isinstance(
            catalog["/AcroForm"], DictionaryObject
        ):
            return None
        acroform = cast(DictionaryObject, catalog[NameObject("/AcroForm")])
        if "/Fields" not in acroform:
            return None

        interim = cast(
            DictionaryObject,
            cast(ArrayObject, acroform[NameObject("/Fields")])[0].get_object(),
        )
        interim[NameObject("/T")] = TextStringObject(name)
        return interim

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
        self.stream.seek(0)
        pdf_data = self.stream.read()
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

    def _get_named_destinations(
        self,
        *,
        tree: Optional[DictionaryObject] = None,
        retval: Optional[dict[str, Destination]] = None,
        visited: Optional[set[int]] = None,
    ) -> dict[str, Destination]:
        """Override from PdfDocCommon. In the reader we can assume this is
        static, but not in the writer.
        """
        if tree or retval:
            return super()._get_named_destinations(tree=tree, retval=retval, visited=visited)

        if self._named_destinations_cache is None:
            self._named_destinations_cache = super()._get_named_destinations()
        return self._named_destinations_cache
