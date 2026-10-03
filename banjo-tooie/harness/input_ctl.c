/* Minimal mupen64plus input plugin whose pad state is set from the host process
   through exported globals (ctypes: c_uint32.in_dll(lib, "ctl_buttons")). */
#include <string.h>
#define M64P_PLUGIN_PROTOTYPES 1
#include <mupen64plus/m64p_types.h>
#include <mupen64plus/m64p_plugin.h>

#define EXPORT __attribute__((visibility("default")))

EXPORT volatile unsigned int ctl_buttons = 0; /* raw BUTTONS.Value: low 16 bits buttons, X/Y bytes above */
EXPORT volatile int ctl_reads = 0;
static CONTROL *g_controls;

EXPORT m64p_error PluginStartup(m64p_dynlib_handle h, void *ctx, void (*dbg)(void *, int, const char *)) { return M64ERR_SUCCESS; }
EXPORT m64p_error PluginShutdown(void) { return M64ERR_SUCCESS; }
EXPORT m64p_error PluginGetVersion(m64p_plugin_type *t, int *v, int *api, const char **name, int *caps) {
    if (t) *t = M64PLUGIN_INPUT; if (v) *v = 0x020500; if (api) *api = 0x020100;
    if (name) *name = "ctl input"; if (caps) *caps = 0; return M64ERR_SUCCESS;
}
EXPORT void ControllerCommand(int c, unsigned char *cmd) {}
EXPORT void GetKeys(int c, BUTTONS *keys) {
    if (c == 0) { keys->Value = ctl_buttons; ctl_reads++; } else keys->Value = 0;
}
EXPORT volatile int ctl_init = 0;
EXPORT void InitiateControllers(CONTROL_INFO info) {
    ctl_init++;
    g_controls = info.Controls;
    for (int i = 0; i < 4; i++) { g_controls[i].Present = (i == 0); g_controls[i].RawData = 0; g_controls[i].Plugin = PLUGIN_NONE; }
}
EXPORT void ReadController(int c, unsigned char *cmd) {}
EXPORT int RomOpen(void) { return 1; }
EXPORT void RomClosed(void) {}
EXPORT void SDL_KeyDown(int k, int s) {}
EXPORT void SDL_KeyUp(int k, int s) {}
