import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List, Tuple

import httpx

logger = logging.getLogger(__name__)

class Searchbook:
    API_ENDPOINT = "https://audit.portico.org/Portico/rest/au/getAuList"
    """Asynchronous worker executing concurrent HTTP fetches."""
    def __init__(self, driver: Any, max_concurrent_request: int = 10)->None:
        self.driver = driver
        self.semaphore = asyncio.Semaphore(max_concurrent_request)
        self.header, self.cookies = self._extract_auth_context()

    def _extract_auth_context(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Extracts cookies and session headers pythonically."""
        selenium_cookies = self.driver.get_cookies()
        cookie_dict = {c["name"]:c["value"] for c in selenium_cookies}
        header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        }
        return header, cookie_dict

    async def _fetch_single_key_Word(self, client: httpx.AsyncClient, row_idx: int, batch_name: str, keyword: str)->Dict[str, Any]:
        """
                Fetches metadata for a single keyword with semaphore throttling.
        """
        json_data = {
            'page': 0,
            'contentType': 'E-Book Content',
            'loviLabel': None,
            'alphabet': 'All',
            'providerId': None,
            'search': keyword,
            'searchView': False,
            'volume': None,
            'issue': None,
            'renderAlphabetPagination': False,
        }

        async with self.semaphore:
            logger.info(f"Posting search query for the ISBN {keyword}")
            try:
                response = await client.post(self.API_ENDPOINT, json=json_data)
                response.raise_for_status()
                json_response = response.json()
                content_list_json = json_response["data"]["content"]
                #print(content_list_json)
                if content_list_json:
                    providers = [{"provider": item["providerName"]} for item in content_list_json]
                    return {"row_idx": row_idx, "batch_name":batch_name, "isbn":keyword, "data":providers, "error": "none"}
                else:
                    return {"row_idx": row_idx, "batch_name":batch_name, "isbn":keyword, "data": "Not Available", "error": "none"}
            except Exception as err:
                logger.warning(f"Fetch failed for the Batch {batch_name} ISBN {keyword} row {row_idx}: error {err}")
                return {"row_id": row_idx, "data": None, "error":str(err)}


    async def stream_request(self, indexed_input: List[Tuple[int, str, str]]) -> AsyncGenerator[Dict[str, Any], None]:
        """
             Async Generator yielding results as they resolve.

            Yields:
                Dict[str, Any]: Scaled payload containing row index, response data, and errors.
        """
        timeout_config = httpx.Timeout(15.0, connect=5.0, read=20.0)

        async with httpx.AsyncClient(headers=self.header, cookies=self.cookies, timeout=timeout_config,
                                     follow_redirects=True) as client:
            task = [asyncio.create_task(self._fetch_single_key_Word(client, row_idx, batch_name, kw)) for row_idx, batch_name, kw in indexed_input]

            # asyncio.as_completed yields tasks in order of RESOLUTION, not dispatch!
            for completed_task in asyncio.as_completed(task):
                result = await completed_task
                yield result # <--- Yields immediately! Zero list buffering in RAM.



async def main():
    from test_login_manager import driver
    search_book = Searchbook(driver)
    # print(search_book.header)
    # print(search_book.cookies)
    # indexed_input = [(2, '9780915027002'), (3, '9780915027019'), (4, '9780915027026'), (5, '9789630538329'),
    #                  (6, '9789630538954'), (7, '9789630541305'), (8, '9789630543668'), (9, '9789630543675'),
    #                  (10, '9789630548441')]
    # results = search_book.stream_request(indexed_input=indexed_input)
    # async for result in results:
    #     print(result)


if __name__ == "__main__":
    asyncio.run(main())
