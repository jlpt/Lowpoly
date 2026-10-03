/* No-op mupen64plus video plugin: lets the core run headless at full speed. */
#define M64P_PLUGIN_PROTOTYPES 1
#include <mupen64plus/m64p_types.h>
#include <mupen64plus/m64p_plugin.h>
#define EXPORT __attribute__((visibility("default")))
static GFX_INFO g_info;
EXPORT m64p_error PluginStartup(m64p_dynlib_handle h, void *c, void (*d)(void *, int, const char *)) { return M64ERR_SUCCESS; }
EXPORT m64p_error PluginShutdown(void) { return M64ERR_SUCCESS; }
EXPORT m64p_error PluginGetVersion(m64p_plugin_type *t, int *v, int *api, const char **n, int *caps) {
    if (t) *t = M64PLUGIN_GFX; if (v) *v = 0x020500; if (api) *api = 0x020200; if (n) *n = "null video"; if (caps) *caps = 0; return M64ERR_SUCCESS; }
EXPORT void ChangeWindow(void) {}
EXPORT int InitiateGFX(GFX_INFO info) { g_info = info; return 1; }
EXPORT void MoveScreen(int x, int y) {}
EXPORT void ProcessDList(void) { *g_info.MI_INTR_REG |= 0x20; g_info.CheckInterrupts(); }
EXPORT void ProcessRDPList(void) { *g_info.DPC_STATUS_REG &= ~0x0002; *g_info.MI_INTR_REG |= 0x20; g_info.CheckInterrupts(); }
EXPORT void RomClosed(void) {}
EXPORT int RomOpen(void) { return 1; }
EXPORT void ShowCFB(void) {}
EXPORT void UpdateScreen(void) {}
EXPORT void ViStatusChanged(void) {}
EXPORT void ViWidthChanged(void) {}
EXPORT void ReadScreen2(void *dest, int *w, int *h, int front) { if (w) *w = 0; if (h) *h = 0; }
EXPORT void SetRenderingCallback(void (*cb)(int)) {}
EXPORT void ResizeVideoOutput(int w, int h) {}
EXPORT void FBRead(unsigned int addr) {}
EXPORT void FBWrite(unsigned int addr, unsigned int size) {}
EXPORT void FBGetFrameBufferInfo(void *p) {}
