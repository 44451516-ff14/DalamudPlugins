import json
import os
import subprocess
from time import time
from sys import argv
from os.path import getmtime
from zipfile import ZipFile, ZIP_DEFLATED

BRANCH = os.environ.get('GITHUB_REF', 'refs/heads/master').split('refs/heads/')[-1]
DOWNLOAD_URL = 'https://github.com/44451516-ff14/DalamudPlugins/raw/{branch}/plugins/{plugin_name}/latest.zip'

DEFAULTS = {
    'IsHide': False,
    'IsTestingExclusive': False,
    'ApplicableVersion': 'any',
}

DUPLICATES = {
    'DownloadLinkInstall': ['DownloadLinkTesting', 'DownloadLinkUpdate'],
}

TRIMMED_KEYS = [
    'Author',
    'Name',
    'Punchline',
    'Description',
    'Changelog',
    'InternalName',
    'AssemblyVersion',
    'RepoUrl',
    'ApplicableVersion',
    'Tags',
    'DalamudApiLevel',
    'IconUrl',
    'ImageUrls',
]

def main():
    existing_last_updates = read_existing_last_updates()

    # extract the manifests from inside the zip files
    master = extract_manifests()

    # trim the manifests
    master = [trim_manifest(manifest) for manifest in master]

    # convert the list of manifests into a master list
    add_extra_fields(master)

    # write the master
    write_master(master)

    # update the LastUpdate field in master
    last_update(existing_last_updates)

def extract_manifests():
    manifests = []

    for dirpath, dirnames, filenames in os.walk('./plugins'):
        if len(filenames) == 0 or 'latest.zip' not in filenames:
            continue
        plugin_name = os.path.basename(dirpath)
        latest_zip = os.path.join(dirpath, 'latest.zip')
        with ZipFile(latest_zip) as z:
            manifest = json.loads(z.read(f'{plugin_name}.json').decode('utf-8'))
            manifests.append(manifest)

    return sorted(manifests, key=lambda manifest: manifest["InternalName"].lower())

def add_extra_fields(manifests):
    for manifest in manifests:
        # generate the download link from the internal assembly name
        manifest['DownloadLinkInstall'] = DOWNLOAD_URL.format(branch=BRANCH, plugin_name=manifest["InternalName"])
        # add default values if missing
        for k, v in DEFAULTS.items():
            if k not in manifest:
                manifest[k] = v
        # duplicate keys as specified in DUPLICATES
        for source, keys in DUPLICATES.items():
            for k in keys:
                if k not in manifest:
                    manifest[k] = manifest[source]
        manifest['DownloadCount'] = 0

def write_master(master):
    # write as pretty json
    with open('pluginmaster.json', 'w', encoding='utf-8') as f:
        json.dump(master, f, indent=4, ensure_ascii=False)

def trim_manifest(plugin):
    return {k: plugin[k] for k in TRIMMED_KEYS if k in plugin}

def last_update(existing=None):
    with open('pluginmaster.json', encoding='utf-8') as f:
        master = json.load(f)
    if existing is None:
        existing = read_existing_last_updates()

    for plugin in master:
        latest = os.path.join('plugins', plugin["InternalName"], 'latest.zip')
        if git_has_changes(latest):
            modified = int(getmtime(latest))
        else:
            modified = existing.get(plugin["InternalName"])
            if modified is None:
                modified = git_last_update(latest)
            if modified is None:
                modified = int(getmtime(latest))

        if 'LastUpdate' not in plugin or modified != int(plugin['LastUpdate']):
            plugin['LastUpdate'] = str(modified)

    with open('pluginmaster.json', 'w', encoding='utf-8') as f:
        json.dump(master, f, indent=4, ensure_ascii=False)

def read_existing_last_updates():
    if not os.path.exists('pluginmaster.json'):
        return {}

    with open('pluginmaster.json', encoding='utf-8') as f:
        try:
            master = json.load(f)
        except json.JSONDecodeError:
            return {}

    return {
        plugin["InternalName"]: int(plugin["LastUpdate"])
        for plugin in master
        if "InternalName" in plugin and "LastUpdate" in plugin
    }

def git_last_update(path):
    try:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%ct', '--', path],
            check=True,
            capture_output=True,
            encoding='utf-8',
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    timestamp = result.stdout.strip()
    return int(timestamp) if timestamp else None

def git_has_changes(path):
    try:
        result = subprocess.run(
            ['git', 'diff', '--quiet', '--', path],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False

    return result.returncode == 1

if __name__ == '__main__':
    main()
