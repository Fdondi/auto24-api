import json
import os
import pickle
import random
import time
from typing import Union

import requests
from bs4 import BeautifulSoup
from fake_headers import Headers

from auto24_api.abstract_query import AbstractQuery
from auto24_api.responses import Auto24APISearchResponse
from auto24_api.utils.exceptions import (
    DataNotFoundException,
    InvalidArgsException,
    ReCaptchaRequiredException,
)
from auto24_api.utils.query_encoder_factory import QueryEncoderFactory


class Auto24API:
    def __init__(
        self,
        use_session=True,
        bypass_captcha=False,
        headers: Union[None, dict] = None,
        proxies=None,
        wait_range=(2, 5),
        max_retries=3,
        lang="fr",
        tmp_dir=".",
    ):
        """
        Args:
            use_session (bool, optional): Whether to use Python Requests
                session in order to keep cookies. When True, the session is
                saved to ".autoapi/tmp/". Defaults to True.
            bypass_captcha (bool, optional): Automatically tries to complete
                the reCAPTCHA. Defaults to False.
            headers (Union[None, dict], optional): Python Requests headers.
                When left empty, headers will be autogenerated. Defaults to
                None.
            proxies (_type_, optional): Python Requests proxies. Defaults to
                None.
            wait_range (tuple, optional): A random wait time in seconds
                between the provided interval will be used between requests.
                Defaults to (2, 5).
            max_retries (int, optional): The number of retries if it failed to
                fetch the data. Defaults to 3.
            lang (str, optional): The translated version of the AutoScout24
                language ("fr", "de" or "it"). Defaults to "fr".
            tmp_dir (str, optional): The directory where to save the temporary
                files (".auto24api"). Defaults to ".".

        Raises:
            InvalidLanguageException: _description_
        """
        self._use_session = use_session
        self._bypass_captcha = bypass_captcha
        self._headers = self._get_headers() if headers is None else headers
        self._proxies = proxies
        if lang not in ["fr", "de", "it"]:
            raise InvalidArgsException(
                (
                    "The provided 'lang' is invalid. Choose from "
                    "'fr', 'de' and 'it'."
                )
            )
        else:
            self._lang = lang
        if len(wait_range) != 2 or wait_range[0] > wait_range[1]:
            raise InvalidArgsException(
                (
                    "The provided 'wait_range' is invalid. Length must be "
                    "equal to 2 and first element must be greater than the "
                    "second."
                )
            )
        self._wait_range = wait_range
        self._max_retries = max_retries
        self._tmp_dir = tmp_dir
        self._session = self._load_session()

    @property
    def _LIST_URL(self) -> str:
        LANG_MAP = {
            "fr": "fr/voitures",
            "de": "de/autos",
            "it": "it/automobili",
        }
        return f"https://www.autoscout24.ch/{LANG_MAP[self._lang]}/s"

    @property
    def _SESSION_FILENAME(self) -> str:
        return "session.pkl"

    @property
    def _tmp_path(self) -> str:
        return os.path.join(self._tmp_dir, ".auto24api", "tmp")

    @property
    def _session_file_path(self) -> str:
        return os.path.join(self._tmp_path, self._SESSION_FILENAME)

    def _load_session(self) -> requests.Session:
        if self._use_session and os.path.isfile(self._session_file_path):
            with open(self._session_file_path, "rb") as f:
                return pickle.load(f)
        return requests.Session(headers=self._headers, proxies=self._proxies)

    def _save_session(self) -> requests.Session:
        if not os.path.isdir(self._tmp_path):
            os.makedirs(self._tmp_path)
        with open(self._session_file_path, "wb") as f:
            pickle.dump(self._session, f)

    def _get(self, base_url, query_params: str) -> requests.Response:
        print(f"{base_url}?{query_params}")
        res = self._session.get(
            f"{base_url}?{query_params}",
            headers=self._headers,
            proxies=self._proxies,
        )
        if self._use_session:
            self._save_session()
        return res

    def search_list(self, config: AbstractQuery) -> Auto24APISearchResponse:
        tries = 0
        while tries < self._max_retries:
            res = self._get(self._LIST_URL, QueryEncoderFactory(config).data)
            soup = BeautifulSoup(res.content, "html.parser")
            # Check if recaptcha is required
            if soup.find("div", attrs={"id": "captcha"}) or soup.find(
                "title", string="Anti-Bot Captcha"
            ):
                raise ReCaptchaRequiredException()
            # Extract data
            script_tag = soup.find("script", attrs={"id": "initial-state"})
            if not script_tag:
                tries += 1
                with open("out.html", "w") as f:
                    f.write(res.text)
                # Problem might with invalid headers
                self._headers = self._get_headers()
                time.sleep(random.uniform(*self._wait_range))
                continue
            data = json.loads(self._parsejs_to_json(script_tag.text))
            return Auto24APISearchResponse(
                raw=data,
                stats=data["search"]["stats"],
                search_results=data["searchResults"],
            )
        raise DataNotFoundException()

    def listing_details(self, config: AbstractQuery):
        self._get(self._BASE_URL, QueryEncoderFactory(config).data)

    def _parsejs_to_json(self, js: str) -> str:
        js = js.replace("window.INITIAL_STATE = ", "")
        js = js.replace("undefined", "null")
        js = js.replace("};", "}")
        return js

    def _get_headers(self) -> dict[str, str]:
        return Headers(os="mac", browser="chrome", headers=True).generate()
