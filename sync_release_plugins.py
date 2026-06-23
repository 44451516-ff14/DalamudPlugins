import argparse
import json
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile


GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class PluginRelease:
    internal_name: str
    source: str
    repo: str
    asset_name: str | None = None
    asset_prefix: str | None = None


PLUGINS = [
    PluginRelease(
        internal_name="BossMod",
        source="github_release",
        repo="44451516/ffxiv_bossmod",
        asset_name="latest.zip",
    ),
    PluginRelease(
        internal_name="BossModReborn",
        source="github_release",
        repo="44451516-ff14/BossmodRebornCN",
        asset_prefix="BossModReborn-",
    ),
    PluginRelease(
        internal_name="JobBars",
        source="local",
        repo="0ceal0t/JobBars",
    ),
    PluginRelease(
        internal_name="PartyIcons",
        source="github_release",
        repo="44451516-ff14/xivPartyIcons",
        asset_prefix="PartyIcons-",
    ),
    PluginRelease(
        internal_name="PeepingTom",
        source="local",
        repo="Caraxi/PeepingTom",
    ),
    PluginRelease(
        internal_name="ReActionEx",
        source="dalamud_repo",
        repo="https://puni.sh/api/repository/taurenkey",
    ),
]


def main():
    parser = argparse.ArgumentParser(description="Sync selected plugins from GitHub releases.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch release metadata and validate selected assets without writing plugin zips.",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    for plugin in PLUGINS:
        if plugin.source == "local":
            print(f"{plugin.internal_name}: keeping local plugins/{plugin.internal_name}/latest.zip")
            continue

        asset = fetch_plugin_asset(plugin, token)
        print(f"{plugin.internal_name}: {asset['version']} -> {asset['name']}")
        if not args.dry_run:
            sync_plugin_asset(plugin, asset, token if plugin.source == "github_release" else None)


def fetch_plugin_asset(plugin, token=None):
    if plugin.source == "github_release":
        release = fetch_latest_release(plugin.repo, token)
        asset = select_release_asset(plugin, release)
        asset["version"] = release.get("tag_name")
        return asset

    if plugin.source == "dalamud_repo":
        return fetch_dalamud_repo_asset(plugin, token)

    raise ValueError(f"Unknown sync source {plugin.source} for {plugin.internal_name}")


def fetch_latest_release(repo, token=None):
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    with open_url(url, token) as response:
        return json.loads(response.read().decode("utf-8"))


def select_release_asset(plugin, release):
    assets = release.get("assets", [])
    if plugin.asset_name:
        for asset in assets:
            if asset.get("name") == plugin.asset_name:
                return asset
        raise ValueError(f"No release asset named {plugin.asset_name} for {plugin.internal_name}")

    for asset in assets:
        name = asset.get("name", "")
        if name.startswith(plugin.asset_prefix or "") and name.endswith(".zip"):
            return asset

    raise ValueError(f"No release zip asset for {plugin.internal_name}")


def fetch_dalamud_repo_asset(plugin, token=None):
    with open_url(plugin.repo, token) as response:
        plugins = json.loads(response.read().decode("utf-8"))

    for manifest in plugins:
        if manifest.get("InternalName") != plugin.internal_name:
            continue

        download_url = manifest.get("DownloadLinkInstall") or manifest.get("DownloadLinkUpdate")
        if not download_url:
            raise ValueError(f"No download link for {plugin.internal_name} in {plugin.repo}")

        return {
            "name": f"{plugin.internal_name}-{manifest.get('AssemblyVersion', 'latest')}.zip",
            "browser_download_url": download_url,
            "updated_at": manifest.get("LastUpdate"),
            "version": manifest.get("AssemblyVersion"),
        }

    raise ValueError(f"No manifest for {plugin.internal_name} in {plugin.repo}")


def sync_plugin_asset(plugin, asset, token=None):
    download_url = asset["browser_download_url"]
    target = Path("plugins") / plugin.internal_name / "latest.zip"
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_file:
        temp_path = Path(temp_file.name)

    try:
        download_file(download_url, temp_path, token)
        validate_plugin_zip(temp_path, plugin.internal_name)
        set_release_mtime(temp_path, asset)
        shutil.move(str(temp_path), target)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def download_file(url, target, token=None):
    with open_url(url, token) as response, open(target, "wb") as output:
        shutil.copyfileobj(response, output)


def validate_plugin_zip(path, internal_name):
    manifest_name = f"{internal_name}.json"
    with ZipFile(path) as z:
        if manifest_name not in z.namelist():
            raise ValueError(f"{path} does not contain root manifest {manifest_name}")

        manifest = json.loads(z.read(manifest_name).decode("utf-8"))

    actual = manifest.get("InternalName")
    if actual != internal_name:
        raise ValueError(f"{path} manifest InternalName is {actual}, expected {internal_name}")

    return manifest


def set_release_mtime(path, asset):
    timestamp = asset.get("updated_at") or asset.get("created_at")
    if not timestamp:
        return

    if isinstance(timestamp, int) or str(timestamp).isdigit():
        mtime = int(timestamp)
    else:
        mtime = int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp())
    os.utime(path, (mtime, mtime))


def open_url(url, token=None):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "DalamudPlugins-release-sync",
        },
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    return urllib.request.urlopen(request, timeout=60)


if __name__ == "__main__":
    main()
