from pathlib import Path

Import("env")

PROJECT_DIR = Path(env.subst("$PROJECT_DIR"))


def prepend_include(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text()
    if "return NULL;" not in text or "#include <stddef.h>" in text:
        return
    path.write_text("#include <stddef.h>\n\n" + text)


def patch_generator(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text()
    old = "        text = common.cfmt_string(f'''\n            const void *esp_ipa_pipeline_get_config(const char *name)\n"
    new = "        text = common.cfmt_string(f'''\n            #include <stddef.h>\n\n            const void *esp_ipa_pipeline_get_config(const char *name)\n"
    if old in text:
        path.write_text(text.replace(old, new))


patch_generator(PROJECT_DIR / "managed_components/espressif__esp_ipa/tools/config/esp_ipa_config.py")
prepend_include(PROJECT_DIR / ".pio/build/esp32-p4/esp-idf/espressif__esp_ipa/esp_video_ipa_config.c")
