#!/usr/bin/env python3
import sys, os, shutil

if len(sys.argv) != 2:
    sys.exit("usage: python3 apply_rollingshutterskew_patch.py <absolute AOSP root>")

root = sys.argv[1]
if not os.path.isabs(root):
    sys.exit(f"root must be an absolute path, got: {root}")

base = os.path.join(root, "frameworks/av/services/camera/libcameraservice")
HDR  = os.path.join(base, "common/CameraProviderManager.h")
CPP  = os.path.join(base, "common/CameraProviderManager.cpp")
AIDL = os.path.join(base, "common/aidl/AidlProviderInfo.cpp")
HIDL = os.path.join(base, "common/hidl/HidlProviderInfo.cpp")

for f in (HDR, CPP, AIDL, HIDL):
    if not os.path.isfile(f):
        sys.exit(f"missing expected file: {f}")

def backup(path):
    bak = path + ".orig"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)

def read(path):
    with open(path, "r") as fh:
        return fh.read()

def write(path, text):
    with open(path, "w") as fh:
        fh.write(text)

already = []
applied = []
failed = []

# --- 1. header declaration ---
text = read(HDR)
marker = "            status_t fixupRollingShutterSkew();"
if marker in text:
    already.append(HDR)
else:
    anchor = "            status_t fixupMonochromeTags();\n"
    if anchor not in text:
        sys.exit(f"header anchor not found in {HDR} — tree layout differs from expected, aborting with no changes made")
    backup(HDR)
    write(HDR, text.replace(anchor, anchor + marker + "\n", 1))
    applied.append(HDR)

# --- 2. implementation ---
text = read(CPP)
marker = "status_t CameraProviderManager::ProviderInfo::DeviceInfo3::fixupRollingShutterSkew()"
if marker in text:
    already.append(CPP)
else:
    anchor = "status_t CameraProviderManager::ProviderInfo::DeviceInfo3::fixupMonochromeTags() {"
    if anchor not in text:
        sys.exit(f"impl anchor not found in {CPP} — aborting, no changes made to this file")
    func = '''status_t CameraProviderManager::ProviderInfo::DeviceInfo3::fixupRollingShutterSkew() {
    auto& c = mCameraCharacteristics;
    camera_metadata_entry entry = c.find(ANDROID_SENSOR_ROLLING_SHUTTER_SKEW);
    if (entry.count == 0) {
        // Some vendor HALs omit this optional tag when
        // READ_SENSOR_SETTINGS isn't advertised (legal per spec), but
        // some Camera2 clients (e.g. libgcam-based camera apps) assume
        // it is always present and fail hard otherwise. Supply a
        // plausible default (20ms) rather than leaving it absent.
        int64_t skewNs = 20000000;
        status_t res = c.update(ANDROID_SENSOR_ROLLING_SHUTTER_SKEW, &skewNs, 1);
        if (res != OK) {
            ALOGE("%s: Failed to update ROLLING_SHUTTER_SKEW: %s (%d)",
                    __FUNCTION__, strerror(-res), res);
            return res;
        }
    }
    return OK;
}

'''
    backup(CPP)
    write(CPP, text.replace(anchor, func + anchor, 1))
    applied.append(CPP)

# --- 3/4. call sites (AIDL confirmed, HIDL attempted via same anchor) ---
CALL_ANCHOR = '''    status_t res = fixupMonochromeTags();
    if (OK != res) {
        ALOGE("%s: Unable to fix up monochrome tags based for older HAL version: %s (%d)",
                __FUNCTION__, strerror(-res), res);
        return;
    }
'''
CALL_INSERT = '''    res = fixupRollingShutterSkew();
    if (OK != res) {
        ALOGE("%s: Unable to fix up rolling shutter skew tag: %s (%d)",
                __FUNCTION__, strerror(-res), res);
        // non-fatal - continue initialization
    }
'''

for path, label in ((AIDL, "AIDL"), (HIDL, "HIDL")):
    text = read(path)
    if "fixupRollingShutterSkew();" in text:
        already.append(path)
        continue
    if CALL_ANCHOR not in text:
        failed.append((path, label))
        continue
    backup(path)
    write(path, text.replace(CALL_ANCHOR, CALL_ANCHOR + CALL_INSERT, 1))
    applied.append(path)

print("Already patched:", already if already else "none")
print("Applied:        ", applied if applied else "none")
if failed:
    print("\nFAILED to patch (anchor text not found, left untouched):")
    for path, label in failed:
        print(f"  {label}: {path}")
    print("\nPaste the surrounding context of that file's fixupMonochromeTags() call site")
    print("(same sed -n range as before) and I'll give you a manual diff for it.")
    sys.exit(1)

print("\nAll files patched successfully.")
