from pathlib import Path

Import("env")

PROJECT_DIR = Path(env.subst("$PROJECT_DIR"))
BUILD_DIR = Path(env.subst("$BUILD_DIR"))


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
    anchor = "const void *esp_ipa_pipeline_get_config(const char *name)"
    if anchor not in text or "#include <stddef.h>" in text[text.rfind("else:"):]:
        return
    text = text.replace(anchor, "#include <stddef.h>\n\n            " + anchor, 1)
    path.write_text(text)


def patch_esp_ipa(*args, **kwargs) -> None:
    patch_generator(PROJECT_DIR / "managed_components/espressif__esp_ipa/tools/config/esp_ipa_config.py")
    prepend_include(BUILD_DIR / "esp-idf/espressif__esp_ipa/esp_video_ipa_config.c")


patch_esp_ipa()
env.AddPreAction(str(BUILD_DIR / "esp-idf/espressif__esp_ipa/esp_video_ipa_config.c.o"), patch_esp_ipa)
env.AddPreAction(str(BUILD_DIR / "esp-idf/espressif__esp_ipa/libespressif__esp_ipa.a"), patch_esp_ipa)
env.AddPreAction("buildprog", patch_esp_ipa)
