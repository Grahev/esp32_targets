import json
import os


def load_json(filename, default):
    """Read a JSON file. Missing -> default. Corrupt -> moved aside, default.

    A corrupt file is renamed to <name>.corrupt instead of being left in
    place, so the next save can never overwrite the only copy of old data.
    """
    try:
        with open(filename) as f:
            return json.load(f)
    except OSError:
        return default
    except ValueError:
        print(f"Corrupt {filename}, kept as {filename}.corrupt")
        try:
            os.rename(filename, filename + '.corrupt')
        except OSError:
            pass
        return default


def save_json(filename, data):
    """Write via a temp file + rename, so a power cut leaves old or new, never half."""
    tmp = filename + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    try:
        os.rename(tmp, filename)  # atomic replace on LittleFS
    except OSError:
        # FAT can't rename over an existing file
        os.remove(filename)
        os.rename(tmp, filename)
