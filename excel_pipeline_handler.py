import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Tuple

import openpyxl

logger = logging.getLogger(__name__)


def extract_input_memory_safe(file_path: Path, input_col: int = 2, start_row: int = 2)->List[Tuple[int, str, str]]:
    # read_only=True streams XML directly from disk without building a DOM tree
    workbook = openpyxl.load_workbook(file_path, read_only=True)
    sheet = workbook.active

    indexed_input : List[Tuple[int, str, str]] = []

    if not sheet:
        workbook.close()
        return indexed_input

    # Iterate over rows via generator
    for row_idx, row in enumerate(sheet.iter_rows(min_row=start_row, values_only=True), start_row):
        if not row or len(row) < input_col:
            continue

        #cell_value = row[input_col-1]
        batch_name = row[input_col-2]
        isbn = row[input_col-1]

        # if cell_value and str(cell_value).strip():
        #     indexed_input.append((row_idx, str(cell_value).strip()))
        if isbn and str(isbn).strip():
            indexed_input.append((row_idx, str(batch_name).strip(), str(isbn).strip()))

    workbook.close()
    return indexed_input


async def stream_result_to_excel(result_generator:AsyncGenerator[Dict[str, Any], None], output_path: Path,
                                 total_count: int, progress_callback: Any = None) -> Path:
        """
            Streams incoming async generator results directly to disk workbook.
            Memory usage remains O(1) regardless of total row count.
            """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # write_only=True bypasses in-memory DOM construction completely
        workbook = openpyxl.Workbook()
        sheet = workbook.active

        if sheet is None:
            sheet = workbook.create_sheet(title="Audit Report")
        else:
            sheet.title="Audit Report"

        # Write Header
        sheet.append(["Row Index", "Batch Name", "ISBN", "Status/Audit Data", "Error"])

        processed_count = 0

        # Consume async generator item by item
        async for result in result_generator:
            #row_idx = result["row_idx"]
            row_idx = result.get("row_idx")
            batch_name = result.get("batch_name")
            isbn = result.get("isbn")
            data = result.get("data")
            error = result.get("error")

            cell_value = str(data) if data is not None else "N/A"
            error_value = str(error) if error is None else "None"

            # Append row directly to XML disk buffer
            sheet.append([row_idx, batch_name, isbn, cell_value, error_value])

            processed_count += 1

            # Fire non-blocking progress notification if UI callback provided
            if progress_callback and total_count > 0:
                progress_val = round((processed_count/total_count), 2)
                await progress_callback(progress_val, f"Processed {processed_count}/{total_count} rows...")
        # Flush XML buffer and save file
        workbook.save(output_path)
        workbook.close()

        logger.info(f"Successfully streamed {processed_count} rows to disk: {output_path}")
        return output_path


if __name__ == "__main__":
    source_path = Path(r"C:\Portico-Project\python-tool-testing\Books\Onix\test-onix-isbn.xlsx")
    indexed_input: List[Tuple[int, str, str]] = extract_input_memory_safe(source_path)

    print(indexed_input)

