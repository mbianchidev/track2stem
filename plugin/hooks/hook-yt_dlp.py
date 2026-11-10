from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = [
    "yt_dlp.compat._legacy", "yt_dlp.compat._deprecated",
    "yt_dlp.utils._legacy", "yt_dlp.utils._deprecated",
    *collect_submodules("websockets"),
]
hiddenimports += [name for name in ("Cryptodome", "requests", "urllib3", "mutagen", "brotli", "certifi", "curl_cffi")
                  if find_spec(name) is not None]
excludedimports = ["youtube_dl", "youtube_dlc", "ytdlp_plugins", "devscripts", "bundle"]
datas = collect_data_files("yt_dlp_ejs", includes=["**/*.js"])
if find_spec("curl_cffi") is not None:
    datas += collect_data_files("curl_cffi", includes=["cacert.pem"])
