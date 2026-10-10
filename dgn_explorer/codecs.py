"""One codec implementation, retained in the compatibility module."""

from dgn_folder import (
    DEFAULT_LIMIT, EDITOR_FORMATS, EDITOR_LIMIT, FORMAT, FolderStore, MemoryStore, attribute_sets_view, decode_stream, digest,
    editor_decode, editor_encode, editor_plain_safe, editor_text,
    editing_contract, element_chunks_view, encode_stream, extract, extract_memory,
    file_digest,
    hydrate_text, inside, inspect_dgn, load_manifest, ole_reader, open_dgn, read_limited,
    readable_bytes, rebuild, text_view, view_bytes, write_view,
    ELEMENT_TYPES, TABLE_LEVELS, LINKAGE_NAMES, BECXML_MAGIC,
    xml_fragment_view, xml_fragment_bytes, becxml_view, becxml_bytes, ecxd_view,
    model_index_view, model_header_view, design_header_view, dgn_store_checksum,
    record_core_view, table_record_view, matrix_view, dgn_store_view, xdata_view,
    tag_view, gcs_view,
)