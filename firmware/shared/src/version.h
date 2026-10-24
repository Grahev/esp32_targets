// Firmware version, shared by the hub and the nodes. Bump all three numbers
// together; the hub shows "update available" for nodes on an older version.
#pragma once

#define TARGETS_FW_MAJOR 2
#define TARGETS_FW_MINOR 0
#define TARGETS_FW_PATCH 0

#define TARGETS_STR2(x) #x
#define TARGETS_STR(x) TARGETS_STR2(x)
#define TARGETS_FW_VERSION \
  TARGETS_STR(TARGETS_FW_MAJOR) "." TARGETS_STR(TARGETS_FW_MINOR) "." TARGETS_STR(TARGETS_FW_PATCH)
