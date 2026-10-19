"""Record portable Docker identities from the actual offline image archive."""
import json
from pathlib import PurePosixPath
import tarfile


def archive_identities(archive, inventory):
    metadata = {}
    with tarfile.open(archive, 'r|gz') as stream:
        for member in stream:
            if member.name in ('index.json', 'manifest.json'):
                metadata[member.name] = json.load(stream.extractfile(member))
    by_tag = {}
    for image in metadata.get('manifest.json', []):
        config_id = 'sha256:' + PurePosixPath(image['Config']).name.removesuffix('.json')
        for tag in image.get('RepoTags', []):
            by_tag.setdefault(tag, []).append(config_id)
    for descriptor in metadata.get('index.json', {}).get('manifests', []):
        tag = descriptor.get('annotations', {}).get('io.containerd.image.name', '')
        tag = tag.removeprefix('docker.io/').removeprefix('library/')
        if tag:
            by_tag.setdefault(tag, []).append(descriptor['digest'])
    for entry in inventory:
        assert entry['image'] in by_tag, 'Missing archived image: ' + entry['image']
        entry['acceptedIds'] = list(dict.fromkeys([entry['id'], *by_tag[entry['image']]]))
    return inventory
