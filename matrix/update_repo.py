#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kodi addons.xml generator with support for repository folders whose name
is different from the add-on id (e.g. binary add-ons such as
inputstream.ffmpegdirect+windows-x86_64).

For such folders Kodi needs <path> inside xbmc.addon.metadata / kodi.addon.metadata.
The path is only injected into the generated addons.xml; source addon.xml files
are not modified.
"""

import os
import hashlib
import xml.etree.ElementTree as ET

DIR_PATH = os.path.dirname(os.path.realpath(__file__))
ADDONS_XML_FILE = os.path.join(DIR_PATH, "addons.xml")
ADDONS_MD5_FILE = os.path.join(DIR_PATH, "addons.xml.md5")

METADATA_POINTS = {"xbmc.addon.metadata", "kodi.addon.metadata"}


class Generator:
    def __init__(self):
        self._generate_addons_file()
        self._generate_md5_file()
        self._generate_zip_sha256_files()
        print("✔ Fertig: addons.xml, addons.xml.md5 und ZIP-SHA256-Dateien wurden aktualisiert.")

    @staticmethod
    def _indent(elem, level=0):
        """Simple pretty-printer compatible with older Python 3 versions."""
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            for child in elem:
                Generator._indent(child, level + 1)
            if not elem[-1].tail or not elem[-1].tail.strip():
                elem[-1].tail = indent
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent

    @staticmethod
    def _find_metadata_extension(root):
        for ext in root.findall("extension"):
            if ext.get("point") in METADATA_POINTS:
                return ext
        return None

    @staticmethod
    def _inject_repository_path(root, folder_name, addon_path):
        """
        Add repository-only <path> when physical folder != addon id.

        Kodi interprets this path relative to <datadir>.  Example:
          inputstream.ffmpegdirect+windows-x86_64/
          inputstream.ffmpegdirect-21.3.8.zip
        """
        addon_id = root.get("id")
        version = root.get("version")
        if not addon_id or not version:
            raise ValueError("addon.xml enthält keine gültige id/version")

        if folder_name == addon_id:
            return False

        metadata = Generator._find_metadata_extension(root)
        if metadata is None:
            raise ValueError("keine xbmc.addon.metadata/kodi.addon.metadata Extension gefunden")

        zip_name = f"{addon_id}-{version}.zip"
        zip_path = os.path.join(addon_path, zip_name)
        repo_path = f"{folder_name}/{zip_name}"

        # Replace an existing repository-only path to avoid duplicates.
        old_path = metadata.find("path")
        if old_path is not None:
            metadata.remove(old_path)

        path_element = ET.Element("path")
        path_element.text = repo_path
        metadata.insert(0, path_element)

        if os.path.isfile(zip_path):
            print(f"  ↳ Pfad: {addon_id} -> {repo_path}")
        else:
            print(f"⚠ ZIP fehlt: {zip_path}")
            print(f"  ↳ Pfad wird trotzdem eingetragen: {repo_path}")

        return True

    def _generate_addons_file(self):
        addons_root = ET.Element("addons")
        count = 0
        mapped = 0

        for folder_name in sorted(os.listdir(DIR_PATH), key=str.lower):
            addon_path = os.path.join(DIR_PATH, folder_name)

            if not os.path.isdir(addon_path):
                continue
            if folder_name.endswith((".svn", ".git")):
                continue

            addon_xml_path = os.path.join(addon_path, "addon.xml")
            if not os.path.isfile(addon_xml_path):
                # Same behavior as the old script, but without noisy traceback.
                continue

            try:
                tree = ET.parse(addon_xml_path)
                root = tree.getroot()

                if root.tag != "addon":
                    raise ValueError("Root-Element ist nicht <addon>")

                if self._inject_repository_path(root, folder_name, addon_path):
                    mapped += 1

                addons_root.append(root)
                count += 1

            except Exception as exc:
                print(f"⚠ Ausschluss von {addon_path} wegen Fehler: {exc}")

        self._indent(addons_root)
        xml_body = ET.tostring(addons_root, encoding="unicode", short_empty_elements=True)
        content = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml_body + "\n"
        self._save_file(content.encode("utf-8"), ADDONS_XML_FILE)

        print(f"✔ {count} Add-ons eingelesen, {mapped} abweichende Repository-Pfade eingetragen.")

    def _generate_md5_file(self):
        try:
            with open(ADDONS_XML_FILE, "rb") as f:
                digest = hashlib.md5(f.read()).hexdigest()
            self._save_file(digest.encode("ascii"), ADDONS_MD5_FILE)
        except Exception as exc:
            print(f"❌ Fehler beim Erstellen von addons.xml.md5: {exc}")

    def _generate_zip_sha256_files(self):
        """Erzeugt/aktualisiert <addon-id>-<version>.zip.sha256 für jede aktuelle Add-on-ZIP."""
        created = 0
        missing = 0

        for folder_name in sorted(os.listdir(DIR_PATH), key=str.lower):
            addon_path = os.path.join(DIR_PATH, folder_name)
            if not os.path.isdir(addon_path) or folder_name.endswith((".svn", ".git")):
                continue

            addon_xml_path = os.path.join(addon_path, "addon.xml")
            if not os.path.isfile(addon_xml_path):
                continue

            try:
                root = ET.parse(addon_xml_path).getroot()
                addon_id = root.get("id")
                version = root.get("version")
                if root.tag != "addon" or not addon_id or not version:
                    raise ValueError("addon.xml enthält keine gültige id/version")

                zip_name = f"{addon_id}-{version}.zip"
                zip_path = os.path.join(addon_path, zip_name)
                sha256_path = zip_path + ".sha256"

                if not os.path.isfile(zip_path):
                    print(f"⚠ SHA-256 übersprungen, ZIP fehlt: {zip_path}")
                    missing += 1
                    continue

                digest = hashlib.sha256()
                with open(zip_path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        digest.update(chunk)

                self._save_file(digest.hexdigest().encode("ascii"), sha256_path)
                print(f"✔ SHA-256: {folder_name}/{zip_name}.sha256")
                created += 1

            except Exception as exc:
                print(f"⚠ SHA-256-Fehler bei {addon_path}: {exc}")

        print(f"✔ {created} SHA-256-Dateien erstellt/aktualisiert, {missing} ZIP(s) fehlten.")

    @staticmethod
    def _save_file(data, filename):
        try:
            with open(filename, "wb") as f:
                f.write(data)
        except Exception as exc:
            print(f"❌ Fehler beim Speichern von {filename}: {exc}")
            raise


if __name__ == "__main__":
    Generator()
