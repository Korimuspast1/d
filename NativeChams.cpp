#define NOMINMAX
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include "features/visuals/chams/native/NativeChams.h"

#include "core/console/Console.h"
#include "core/globals/Game.h"
#include "core/math/Math.h"
#include "core/memory/Memory.h"
#include "core/player/PlayerCache.h"
#include "core/player/PlayerLists.h"
#include "core/roblox/instance/Instance.h"
#include "core/roblox/offsets/Offsets.h"
#include "core/runtime/Runtime.h"
#include "features/aim/silent/raycast_silent/silent/BoundSilent.h"
#include "features/games/phantom_forces/PhantomForces.h"
#include "features/lua/vm/call_gate/CallGate.h"
#include "features/lua/vm/instance_create/InstanceCreate.h"
#include "features/misc/sky/SkyShader.h"
#include "features/visuals/chams/force/ForceMaterial.h"
#include "features/visuals/chams/mesh/MeshChams.h"
#include "layout/Settings.h"

#include <Windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>

#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <algorithm>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#ifndef CFG_CALL_TARGET_VALID
#define CFG_CALL_TARGET_VALID 0x00000001
#endif

#pragma comment(lib, "d3dcompiler.lib")

namespace Cheat {
namespace Visuals {
namespace NativeChams {
namespace {

constexpr int k_slot_create_buf = 3;
constexpr int k_slot_create_il = 11;
constexpr int k_slot_create_vs = 12;
constexpr int k_slot_create_ps = 15;
constexpr int k_slot_create_blend = 20;
constexpr int k_slot_create_dss = 21;
constexpr int k_slot_create_raster = 22;
constexpr int k_slot_vscb = 7;
constexpr int k_slot_psset = 9;
constexpr int k_slot_vsset = 11;
constexpr int k_slot_drawidx = 12;
constexpr int k_slot_pscb = 16;
constexpr int k_slot_ilset = 17;
constexpr int k_slot_vbset = 18;
constexpr int k_slot_ibset = 19;
constexpr int k_slot_topo = 24;
constexpr int k_slot_omset = 33;
constexpr int k_slot_blendset = 35;
constexpr int k_slot_dssset = 36;
constexpr int k_slot_rsset = 43;
constexpr int k_slot_update = 48;
constexpr int k_slot_psget = 74;
constexpr int k_slot_blendget = 91;
constexpr int k_slot_dssget = 92;
constexpr int k_slot_present = 8;
constexpr int k_slot_dc_draw = 28;
constexpr int k_vt_cap = 510;

constexpr std::uint32_t k_cmd_vs = 1;
constexpr std::uint32_t k_cmd_ps = 2;
constexpr std::uint32_t k_cmd_il = 3;
constexpr std::uint32_t k_cmd_buf = 4;
constexpr std::uint32_t k_cmd_blend = 5;
constexpr std::uint32_t k_cmd_raster = 6;
constexpr std::uint32_t k_cmd_dss = 7;

constexpr int k_max_targets = 512;
constexpr int k_max_ents = 256;
constexpr int k_ent_budget = 2048;

constexpr char k_hlsl[] = R"HLSL(
cbuffer Cham : register(b13)
{
    float4 color;
    float4 glow;
    float time;
    int mode;
    float depth_scale;
    float depth_bias;
};

struct Out
{
    float4 c : SV_TARGET;
    float z : SV_DEPTH;
};

float3 screen_normal(float4 pos)
{
    float2 g = float2(ddx(pos.w), ddy(pos.w)) / max(abs(pos.w), 1e-6) * 480.0;
    return normalize(float3(g, 1.0));
}

float hash21(float2 p)
{
    p = frac(p * float2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return frac(p.x * p.y);
}

float vnoise(float2 p)
{
    float2 i = floor(p);
    float2 f = frac(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + float2(1.0, 0.0));
    float c = hash21(i + float2(0.0, 1.0));
    float d = hash21(i + float2(1.0, 1.0));
    return lerp(lerp(a, b, f.x), lerp(c, d, f.x), f.y);
}

float fbm2(float2 p)
{
    float a = 0.0;
    float w = 0.5;
    [unroll] for (int k = 0; k < 4; ++k)
    {
        a += w * vnoise(p);
        p = p * 2.02 + 7.3;
        w *= 0.5;
    }
    return a;
}

float3 hue_rot(float3 c, float h)
{
    float3 k = float3(0.57735, 0.57735, 0.57735);
    return c * cos(h) + cross(k, c) * sin(h) + k * dot(k, c) * (1.0 - cos(h));
}

float3 lit(float3 fill, float3 N, float amb, float k)
{
    return fill * (amb + saturate(dot(N, normalize(float3(0.45, -0.70, 0.55)))) * k);
}

float3 spec(float3 fill, float3 N, float amb, float k, float p)
{
    float3 L = normalize(float3(0.50, -0.80, 0.35));
    float3 H = normalize(L + float3(0.0, 0.0, 1.0));
    return fill * (amb + saturate(dot(N, L)) * k) + pow(saturate(dot(N, H)), p);
}

void add_glow(inout float3 c, inout float a, float mask)
{
    float w = saturate(mask) * glow.a;
    float t = w / (1.0 + w);
    c = lerp(c, glow.rgb, t);
    c += glow.rgb * t * t * 0.75;
    a = saturate(a + t * (1.0 - a) * 0.9);
}

Out ps_main(float4 pos : SV_POSITION)
{
    float3 fill = color.rgb;
    float a = color.a;
    float3 N = screen_normal(pos);
    float rim = saturate(1.0 - saturate(N.z));
    float rp = pow(abs(rim), 2.4);
    float edge = saturate(length(fwidth(N)) * 2.2);
    float3 N5 = normalize(round(N * 5.0) / 5.0);
    float fe5 = saturate(length(fwidth(N5)) * 3.2);
    float2 uv = pos.xy;
    float3 c = fill;
    float gmask = rp * 0.55 + edge * 0.75;

    switch (mode)
    {
    case 0:
        gmask = rp * 0.55 + edge * 0.8;
        break;
    case 1:
        c = lit(fill, N, 0.32, 0.68);
        gmask = pow(abs(rim), 2.0) * 0.7 + edge * 0.55;
        break;
    case 2:
        c = fill * (0.38 + saturate(N.y) * 0.35);
        gmask = edge * 0.7;
        break;
    case 3:
        c = fill * (0.18 + pow(abs(rim), 1.2) * 0.55);
        a *= saturate(0.10 + pow(abs(rim), 1.2) * 0.9);
        gmask = pow(abs(rim), 1.2) * 0.85 + edge * 0.55;
        break;
    case 4:
        c = spec(fill, N, 0.16, 0.45, 64.0);
        a *= saturate(0.18 + rim * 0.7);
        gmask = pow(abs(rim), 1.5) * 0.9 + edge * 0.6;
        break;
    case 5:
        c = fill * (0.22 + saturate(N.y * 0.4 + 0.2));
        a *= saturate(0.30 + rim * 0.55);
        gmask = pow(abs(rim), 1.35) * 0.8 + fe5 * 0.75;
        break;
    case 6:
        c = hue_rot(fill, rim * 4.0 + edge * 2.0);
        a *= saturate(0.20 + rim * 0.65);
        gmask = pow(abs(rim), 1.4) * 0.8;
        break;
    case 7:
    {
        float n = fbm2(uv * 0.010 + float2(0.0, -time * 0.40));
        n = fbm2(uv * 0.016 + n * 1.4 + time * 0.12);
        float flame = smoothstep(0.30, 0.75, n);
        c = fill * (0.14 + flame * 0.22);
        gmask = flame * 0.9 + rp * 0.35;
    }
        break;
    default:
        c = fill * (0.12 + pow(abs(rim), 0.8) * 0.2);
        gmask = pow(abs(rim), 0.9) * 0.95 + edge * 0.4;
        break;
    }

    add_glow(c, a, gmask);
    Out o;
    o.c = float4(saturate(c), saturate(a));
    o.z = saturate(pos.z * depth_scale + depth_bias);
    return o;
}
)HLSL";

#pragma pack(push, 8)
struct FrameCB {
	float vp[16];
	float cam[3];
	float time;
	int mode;
	float pad[3];
};
static_assert(sizeof(FrameCB) == 96);

struct RemoteState {
	std::uint32_t enabled;
	std::uint32_t cmd;
	std::uint32_t ready;
	std::uint32_t ngeom;
	std::uint64_t device;
	std::uint64_t ctx;
	std::uint64_t orig_present;
	std::uint64_t orig_draw;
	std::uint64_t vs;
	std::uint64_t ps;
	std::uint64_t il;
	std::uint64_t cb;
	std::uint64_t cb1;
	std::uint64_t blend;
	std::uint64_t raster;
	std::uint64_t dss;
	std::uint64_t last_rtv;
	std::uint64_t last_dsv;
	std::uint64_t bytecode;
	std::uint64_t bytecode_len;
	std::uint64_t out_res;
	std::uint64_t init_sys;
	std::uint64_t geoms;
	std::uint32_t entered;
	std::uint32_t draws;
	std::uint32_t creates;
	std::uint32_t busy;
	std::uint32_t stage;
	std::uint32_t il_count;
	FrameCB frame;
	std::uint64_t fn_create_vs;
	std::uint64_t fn_create_ps;
	std::uint64_t fn_create_il;
	std::uint64_t fn_create_buf;
	std::uint64_t fn_create_blend;
	std::uint64_t fn_create_raster;
	std::uint64_t fn_create_dss;
	std::uint64_t fn_vsset;
	std::uint64_t fn_psset;
	std::uint64_t fn_ilset;
	std::uint64_t fn_vbset;
	std::uint64_t fn_ibset;
	std::uint64_t fn_topo;
	std::uint64_t fn_omset;
	std::uint64_t fn_omget;
	std::uint64_t fn_blendset;
	std::uint64_t fn_dssset;
	std::uint64_t fn_rsset;
	std::uint64_t fn_vscb;
	std::uint64_t fn_pscb;
	std::uint64_t fn_update;
	std::uint64_t fn_drawidx;
	std::uint64_t dc;
	std::uint64_t fn_psget;
	std::uint64_t fn_dssget;
	std::uint64_t fn_blendget;
};
#pragma pack(pop)

static_assert(offsetof(RemoteState, cmd) == 0x04);
static_assert(offsetof(RemoteState, device) == 0x10);
static_assert(offsetof(RemoteState, orig_present) == 0x20);
static_assert(offsetof(RemoteState, orig_draw) == 0x28);
static_assert(offsetof(RemoteState, vs) == 0x30);
static_assert(offsetof(RemoteState, last_rtv) == 0x70);
static_assert(offsetof(RemoteState, bytecode) == 0x80);
static_assert(offsetof(RemoteState, geoms) == 0xA0);
static_assert(offsetof(RemoteState, entered) == 0xA8);
static_assert(offsetof(RemoteState, busy) == 0xB4);
static_assert(offsetof(RemoteState, frame) == 0xC0);
static_assert(offsetof(RemoteState, fn_create_vs) == 0x120);
static_assert(offsetof(RemoteState, fn_omget) == 0x190);
static_assert(offsetof(RemoteState, fn_vscb) == 0x1B0);
static_assert(offsetof(RemoteState, fn_pscb) == 0x1B8);
static_assert(offsetof(RemoteState, fn_update) == 0x1C0);
static_assert(offsetof(RemoteState, fn_drawidx) == 0x1C8);
static_assert(offsetof(RemoteState, dc) == 0x1D0);
static_assert(offsetof(RemoteState, fn_psget) == 0x1D8);
static_assert(offsetof(RemoteState, fn_dssget) == 0x1E0);
static_assert(offsetof(RemoteState, fn_blendget) == 0x1E8);
static_assert(sizeof(RemoteState) == 0x1F0);

struct Patch {
	std::uintptr_t at = 0;
	std::uint64_t old = 0;
};

struct Target {
	std::uint64_t geom;
	float color[4];
	float glow[4];
	float time;
	int mode;
	float depth_scale;
	float depth_bias;
};
static_assert(sizeof(Target) == 56);

struct Hook {
	std::uintptr_t state = 0;
	std::uintptr_t geoms = 0;
	std::uintptr_t cave = 0;
	std::size_t cave_n = 0;
	std::uintptr_t present_thunk = 0;
	std::uintptr_t create_stub = 0;
	std::uintptr_t draw_thunk = 0;
	std::uintptr_t device = 0;
	std::uintptr_t ctx = 0;
	std::uintptr_t dc = 0;
	std::uintptr_t dc_vt = 0;
	std::uintptr_t swap = 0;
	std::uintptr_t swap_vt = 0;
	std::uintptr_t vt_mem = 0;
	std::uintptr_t orig_present = 0;
	std::uintptr_t orig_draw = 0;
	std::uintptr_t module = 0;
	std::uintptr_t ps_dxbc = 0;
	std::size_t ps_len = 0;
	Patch patches[16]{};
	int npatch = 0;
	int stage = 0;
	int ntarget = 0;
	int slot = 0;
	int nnode = 0;
	int nent = 0;
	int ndrop = 0;
	int nbind = 0;
	int nswvt = 0;
	int ndcvt = 0;
	bool hooked = false;
	bool depth_rev = false;
	bool cmd_wait = false;
	bool logged = false;
	bool occl_off = false;
	std::uint8_t occl = 0;
};

Hook g{};
auto g_fail = std::chrono::steady_clock::time_point{};
const char* g_why = nullptr;
int g_nunk = 0;
int g_nfc = 0;
int g_npick = 0;
std::uint64_t g_unk_vt = 0;

bool addr_ok(std::uintptr_t a)
{
	return a >= 0x10000ull && a < 0x00007FFFFFFFFFFFull;
}

void append_u64(std::vector<std::uint8_t>& c, std::uint64_t v)
{
	const auto* b = (const std::uint8_t*)&v;
	c.insert(c.end(), b, b + 8);
}

void append_call_rax(std::vector<std::uint8_t>& c)
{
	c.insert(c.end(), { 0xFF, 0xD0 });
}

std::size_t append_jcc32(std::vector<std::uint8_t>& c, std::uint8_t cc)
{
	c.push_back(0x0F);
	c.push_back((std::uint8_t)(0x80 | cc));
	c.insert(c.end(), 4, 0);
	return c.size() - 4;
}

void patch_rel32(std::vector<std::uint8_t>& c, std::size_t at, std::size_t dest)
{
	const std::int32_t rel = (std::int32_t)((std::ptrdiff_t)dest - (std::ptrdiff_t)(at + 4));
	std::memcpy(c.data() + at, &rel, 4);
}

bool mark_cfg(std::uintptr_t t)
{
	static FARPROC proc = nullptr;
	if (!proc)
	{
		const char* mods[] = {
			"kernelbase.dll", "kernel32.dll",
			"api-ms-win-core-memory-l1-1-3.dll"
		};
		for (auto* m : mods)
		{
			HMODULE h = GetModuleHandleA(m);
			if (!h)
				h = LoadLibraryA(m);
			if (!h)
				continue;
			proc = GetProcAddress(h, "SetProcessValidCallTargets");
			if (proc)
				break;
		}
	}
	if (!proc || !g_Memory.GetHandle())
		return false;
	SYSTEM_INFO si{};
	GetSystemInfo(&si);
	const std::size_t page = si.dwPageSize ? (std::size_t)si.dwPageSize : 0x1000u;
	struct Info {
		ULONG_PTR Offset;
		ULONG Flags;
	} info{};
	info.Offset = t & (page - 1);
	info.Flags = CFG_CALL_TARGET_VALID;
	using Fn = BOOL(WINAPI*)(HANDLE, PVOID, SIZE_T, ULONG, void*);
	return ((Fn)proc)(
		g_Memory.GetHandle(),
		(void*)(t & ~((std::uintptr_t)page - 1)),
		page, 1, &info) != 0;
}

bool write_exec(std::uintptr_t at, const void* data, std::size_t n)
{
	if (!addr_ok(at) || !data || !n)
		return false;
	DWORD old = 0;
	const bool changed = g_Memory.Protect(at, n, PAGE_EXECUTE_READWRITE, &old);
	const bool ok = g_Memory.WriteRaw(at, data, n) == n;
	if (changed)
		g_Memory.Protect(at, n, old, nullptr);
	return ok;
}

bool exec_prot(DWORD p)
{
	const DWORD b = p & 0xFF;
	return b == PAGE_EXECUTE || b == PAGE_EXECUTE_READ ||
		b == PAGE_EXECUTE_READWRITE || b == PAGE_EXECUTE_WRITECOPY;
}

std::uintptr_t find_dll_cave(std::size_t need, std::uintptr_t ignore)
{
	static const wchar_t* pref[] = {
		L"winsta.dll", L"win32u.dll", L"uxtheme.dll", L"dwmapi.dll",
		L"msctf.dll", L"TextInputFramework.dll", L"CoreMessaging.dll",
		L"user32.dll", L"imm32.dll", L"gdi32.dll", L"ole32.dll", L"combase.dll",
	};
	for (auto* name : pref)
	{
		const std::uintptr_t mb = g_Memory.GetModuleBase(name);
		if (!mb)
			continue;
		IMAGE_DOS_HEADER dos{};
		if (g_Memory.ReadRaw(mb, &dos, sizeof(dos)) != sizeof(dos) || dos.e_magic != IMAGE_DOS_SIGNATURE)
			continue;
		IMAGE_NT_HEADERS64 nt{};
		if (g_Memory.ReadRaw(mb + (std::uintptr_t)dos.e_lfanew, &nt, sizeof(nt)) != sizeof(nt)
			|| nt.Signature != IMAGE_NT_SIGNATURE)
			continue;
		const std::size_t ms = nt.OptionalHeader.SizeOfImage;
		if (ms < 0x2000)
			continue;
		std::uintptr_t addr = mb + 0x1000;
		const std::uintptr_t to = mb + ms;
		MEMORY_BASIC_INFORMATION mbi{};
		while (addr < to &&
			VirtualQueryEx(g_Memory.GetHandle(), (void*)addr, &mbi, sizeof(mbi)))
		{
			const auto rb = (std::uintptr_t)mbi.BaseAddress;
			const auto rs = (std::size_t)mbi.RegionSize;
			const std::uintptr_t next = rb + rs;
			if (next <= addr)
				break;
			const bool usable = mbi.State == MEM_COMMIT
				&& !(mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))
				&& exec_prot(mbi.Protect);
			if (usable && rs >= need)
			{
				std::vector<std::uint8_t> buf(rs);
				if (g_Memory.ReadRaw(rb, buf.data(), rs) == rs)
				{
					std::size_t run = 0;
					for (std::size_t i = 0; i < rs; ++i)
					{
						if (buf[i] == 0x00 || buf[i] == 0xCC)
							++run;
						else
							run = 0;
						if (run >= need)
						{
							const std::uintptr_t start = rb + i + 1 - run;
							const std::uintptr_t aligned = (start + 0x0F) & ~std::uintptr_t(0x0F);
							if (ignore && aligned == ignore)
								continue;
							if (aligned + need > rb + rs)
								continue;
							auto hit = [&](std::uintptr_t p, std::size_t n)
							{
								return p && aligned < p + n && p < aligned + need;
							};
							if (hit(g.cave, g.cave_n))
								continue;
							if (Cheat::Features::SkyShader::CaveBusy(aligned, need)
								|| Cheat::Features::BoundSilent::CaveBusy(aligned, need)
								|| Cheat::Features::CallGate::CaveBusy(aligned, need)
								|| Cheat::Visuals::ForceMaterial::CaveBusy(aligned, need))
								continue;
							return aligned;
						}
					}
				}
			}
			addr = next;
		}
	}
	return 0;
}

void fail(const char* why)
{
	if (g_why == why)
		return;
	g_why = why;
	console::Log(console::Color::Red, "nativechams: %s", why);
}

std::uintptr_t module_base()
{
	const std::uintptr_t cached = (std::uintptr_t)runtime::ModuleBase();
	if (cached)
		return cached;
	return g_Memory.GetModuleBase(L"RobloxPlayerBeta.exe");
}

std::uintptr_t visual_engine()
{
	const std::uintptr_t base = module_base();
	if (!base)
		return 0;
	const std::uint64_t ve = g_Memory.Read<std::uint64_t>(base + Offsets::VisualEngine::Pointer);
	return g_Memory.IsValid(ve) ? (std::uintptr_t)ve : 0;
}

std::uintptr_t render_view()
{
	const std::uintptr_t ve = visual_engine();
	if (!ve)
		return 0;
	const std::uint64_t rv = g_Memory.Read<std::uint64_t>(ve + Offsets::VisualEngine::RenderView);
	return g_Memory.IsValid(rv) ? (std::uintptr_t)rv : 0;
}

bool want_reverse()
{
	const std::uintptr_t ve = visual_engine();
	if (!ve)
		return g.depth_rev;
	float m[16]{};
	if (g_Memory.ReadRaw(ve + Offsets::VisualEngine::ViewMatrix, m, sizeof(m)) != sizeof(m))
		return g.depth_rev;
	const float zl = std::sqrt(m[8] * m[8] + m[9] * m[9] + m[10] * m[10]);
	const float wl = std::sqrt(m[12] * m[12] + m[13] * m[13] + m[14] * m[14]);
	if (wl < 1e-4f)
		return g.depth_rev;
	return zl < wl * 0.5f;
}

bool find_d3d()
{
	if (g.device && g_Memory.IsValid(g.device) && g.ctx && g_Memory.IsValid(g.ctx) &&
		g.swap && g_Memory.IsValid(g.swap))
		return true;
	const std::uintptr_t base = module_base();
	const std::uintptr_t rv = render_view();
	if (!base || !rv)
		return false;
	const std::uintptr_t wrap = (std::uintptr_t)g_Memory.Read<std::uint64_t>(rv + Offsets::RenderView::DeviceD3D11);
	if (!g_Memory.IsValid(wrap))
		return false;
	if (g_Memory.Read<std::uint64_t>(wrap) != base + Offsets::DeviceD3D11Gfx::VTableRva)
		return false;
	const std::uintptr_t dev = (std::uintptr_t)g_Memory.Read<std::uint64_t>(wrap + Offsets::DeviceD3D11Gfx::DevicePtr);
	const std::uintptr_t ctx = (std::uintptr_t)g_Memory.Read<std::uint64_t>(wrap + Offsets::DeviceD3D11Gfx::ContextPtr);
	const std::uintptr_t swap = (std::uintptr_t)g_Memory.Read<std::uint64_t>(wrap + Offsets::DeviceD3D11Gfx::SwapChainPtr);
	const std::uintptr_t dc = (std::uintptr_t)g_Memory.Read<std::uint64_t>(wrap + Offsets::DeviceD3D11Gfx::ContextObj);
	if (!addr_ok(dev) || !addr_ok(ctx) || !addr_ok(swap) || !addr_ok(dc))
		return false;
	if (g_Memory.Read<std::uint64_t>(dc + 0x18) != ctx)
		return false;
	g.device = dev;
	g.ctx = ctx;
	g.swap = swap;
	g.dc = dc;
	return true;
}
std::uintptr_t vt_fn(std::uintptr_t obj, int slot)
{
	const std::uintptr_t vt = (std::uintptr_t)g_Memory.Read<std::uint64_t>(obj);
	if (!addr_ok(vt))
		return 0;
	const std::uintptr_t fn = (std::uintptr_t)g_Memory.Read<std::uint64_t>(vt + (std::size_t)slot * 8);
	return addr_ok(fn) ? fn : 0;
}

bool compile(const char* entry, const char* model, std::vector<std::uint8_t>& out)
{
	ID3DBlob* blob = nullptr;
	ID3DBlob* err = nullptr;
	const HRESULT hr = D3DCompile(
		k_hlsl, sizeof(k_hlsl) - 1, nullptr, nullptr, nullptr,
		entry, model, D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &blob, &err);
	if (FAILED(hr) || !blob)
	{
		if (err)
		{
			console::Log(console::Color::Red, "nativechams compile: %s", (const char*)err->GetBufferPointer());
			err->Release();
		}
		return false;
	}
	if (err)
		err->Release();
	const auto* p = (const std::uint8_t*)blob->GetBufferPointer();
	out.assign(p, p + blob->GetBufferSize());
	blob->Release();
	return !out.empty();
}


std::vector<std::uint8_t> make_present_thunk(std::uintptr_t state, std::uintptr_t create)
{
	std::vector<std::uint8_t> c;
	c.insert(c.end(), { 0x51, 0x52, 0x41, 0x50, 0x41, 0x51 });
	c.insert(c.end(), { 0x48, 0x83, 0xEC, 0x28 });
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0xFF, 0x80, 0xA8, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x83, 0xB8, 0xB4, 0x00, 0x00, 0x00, 0x00 });
	const std::size_t j_busy = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0xC7, 0x80, 0xB4, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x83, 0x78, 0x04, 0x00 });
	const std::size_t j_nocmd = append_jcc32(c, 0x04);
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, create);
	append_call_rax(c);
	const std::size_t nocmd = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0xC7, 0x80, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 });
	const std::size_t out = c.size();
	c.insert(c.end(), { 0x48, 0x83, 0xC4, 0x28 });
	c.insert(c.end(), { 0x41, 0x59, 0x41, 0x58, 0x5A, 0x59 });
	c.insert(c.end(), { 0x49, 0xBA });
	append_u64(c, state);
	c.insert(c.end(), { 0x4D, 0x8B, 0x5A, 0x20 });
	c.insert(c.end(), { 0x41, 0xFF, 0xE3 });
	patch_rel32(c, j_busy, out);
	patch_rel32(c, j_nocmd, nocmd);
	return c;
}

std::vector<std::uint8_t> make_create_stub(std::uintptr_t state)
{
	std::vector<std::uint8_t> c;
	c.insert(c.end(), { 0x48, 0x83, 0xEC, 0x48 });
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x8B, 0x48, 0x04 });
	c.insert(c.end(), { 0x85, 0xC9 });
	const std::size_t j_none = append_jcc32(c, 0x04);
	c.insert(c.end(), { 0x48, 0xC7, 0x80, 0x90, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x83, 0xF9, 0x01 });
	const std::size_t j_nvs = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0x48, 0x8B, 0x48, 0x10 });
	c.insert(c.end(), { 0x48, 0x8B, 0x90, 0x80, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8B, 0x80, 0x88, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4D, 0x31, 0xC9 });
	c.insert(c.end(), { 0x4C, 0x8D, 0x90, 0x90, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x89, 0x54, 0x24, 0x20 });
	c.insert(c.end(), { 0xFF, 0x90, 0x20, 0x01, 0x00, 0x00 });
	c.insert(c.end(), { 0xE9, 0, 0, 0, 0 });
	const std::size_t j_fin0 = c.size() - 4;
	const std::size_t nvs = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x83, 0xF9, 0x02 });
	const std::size_t j_nps = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0x48, 0x8B, 0x48, 0x10 });
	c.insert(c.end(), { 0x48, 0x8B, 0x90, 0x80, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8B, 0x80, 0x88, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4D, 0x31, 0xC9 });
	c.insert(c.end(), { 0x4C, 0x8D, 0x90, 0x90, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x89, 0x54, 0x24, 0x20 });
	c.insert(c.end(), { 0xFF, 0x90, 0x28, 0x01, 0x00, 0x00 });
	c.insert(c.end(), { 0xE9, 0, 0, 0, 0 });
	const std::size_t j_fin1 = c.size() - 4;
	const std::size_t nps = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x83, 0xF9, 0x03 });
	const std::size_t j_nil = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0x48, 0x8B, 0x48, 0x10 });
	c.insert(c.end(), { 0x48, 0x8D, 0x90, 0x10, 0x03, 0x00, 0x00 });
	c.insert(c.end(), { 0x44, 0x8B, 0x80, 0xBC, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8B, 0x88, 0x80, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x48, 0x8B, 0x80, 0x88, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x48, 0x89, 0x44, 0x24, 0x20 });
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x4C, 0x8D, 0x90, 0x90, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x89, 0x54, 0x24, 0x28 });
	c.insert(c.end(), { 0xFF, 0x90, 0x30, 0x01, 0x00, 0x00 });
	c.insert(c.end(), { 0xE9, 0, 0, 0, 0 });
	const std::size_t j_fin2 = c.size() - 4;
	const std::size_t nil_ = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x83, 0xF9, 0x04 });
	const std::size_t j_nbuf = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0x48, 0x8B, 0x48, 0x10 });
	c.insert(c.end(), { 0x48, 0x8D, 0x90, 0x00, 0x02, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8B, 0x80, 0x98, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4D, 0x85, 0xC0 });
	c.insert(c.end(), { 0x74, 0x24 });
	c.insert(c.end(), { 0x4C, 0x89, 0x80, 0xD8, 0x03, 0x00, 0x00 });
	c.insert(c.end(), { 0x48, 0xC7, 0x80, 0xE0, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x48, 0xC7, 0x80, 0xE8, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8D, 0x80, 0xD8, 0x03, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8D, 0x88, 0x90, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0xFF, 0x90, 0x38, 0x01, 0x00, 0x00 });
	c.insert(c.end(), { 0xE9, 0, 0, 0, 0 });
	const std::size_t j_fin3 = c.size() - 4;
	const std::size_t nbuf = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x83, 0xF9, 0x05 });
	const std::size_t j_nblend = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0x48, 0x8B, 0x48, 0x10 });
	c.insert(c.end(), { 0x48, 0x8D, 0x90, 0x00, 0x02, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8D, 0x80, 0x90, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0xFF, 0x90, 0x40, 0x01, 0x00, 0x00 });
	c.insert(c.end(), { 0xE9, 0, 0, 0, 0 });
	const std::size_t j_fin4 = c.size() - 4;
	const std::size_t nblend = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x83, 0xF9, 0x06 });
	const std::size_t j_nrast = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0x48, 0x8B, 0x48, 0x10 });
	c.insert(c.end(), { 0x48, 0x8D, 0x90, 0x00, 0x02, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8D, 0x80, 0x90, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0xFF, 0x90, 0x48, 0x01, 0x00, 0x00 });
	c.insert(c.end(), { 0xE9, 0, 0, 0, 0 });
	const std::size_t j_fin5 = c.size() - 4;
	const std::size_t nrast = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0x83, 0xF9, 0x07 });
	const std::size_t j_ndss = append_jcc32(c, 0x05);
	c.insert(c.end(), { 0x48, 0x8B, 0x48, 0x10 });
	c.insert(c.end(), { 0x48, 0x8D, 0x90, 0x00, 0x02, 0x00, 0x00 });
	c.insert(c.end(), { 0x4C, 0x8D, 0x80, 0x90, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0xFF, 0x90, 0x50, 0x01, 0x00, 0x00 });
	const std::size_t fin = c.size();
	c.insert(c.end(), { 0x48, 0xB8 });
	append_u64(c, state);
	c.insert(c.end(), { 0xC7, 0x40, 0x04, 0x00, 0x00, 0x00, 0x00 });
	c.insert(c.end(), { 0xFF, 0x80, 0xB0, 0x00, 0x00, 0x00 });
	const std::size_t none = c.size();
	c.insert(c.end(), { 0x48, 0x83, 0xC4, 0x48 });
	c.push_back(0xC3);
	patch_rel32(c, j_none, none);
	patch_rel32(c, j_nvs, nvs);
	patch_rel32(c, j_nps, nps);
	patch_rel32(c, j_nil, nil_);
	patch_rel32(c, j_nbuf, nbuf);
	patch_rel32(c, j_nblend, nblend);
	patch_rel32(c, j_nrast, nrast);
	patch_rel32(c, j_ndss, fin);
	patch_rel32(c, j_fin0, fin);
	patch_rel32(c, j_fin1, fin);
	patch_rel32(c, j_fin2, fin);
	patch_rel32(c, j_fin3, fin);
	patch_rel32(c, j_fin4, fin);
	patch_rel32(c, j_fin5, fin);
	return c;
}

std::vector<std::uint8_t> make_draw_thunk(std::uintptr_t state)
{
	std::vector<std::uint8_t> c;
	auto bytes = [&](std::initializer_list<std::uint8_t> v) { c.insert(c.end(), v); };
	auto disp32 = [&](std::uint32_t v)
	{
		const auto* b = (const std::uint8_t*)&v;
		c.insert(c.end(), b, b + 4);
	};
	auto ld = [&](std::uint8_t modrm, std::uint32_t off)
	{
		bytes({ 0x49, 0x8B, modrm });
		disp32(off);
	};
	auto ld_rax = [&](std::uint32_t off) { ld(0x86, off); };
	auto ld_rdx = [&](std::uint32_t off) { ld(0x96, off); };
	auto ctx = [&] { bytes({ 0x49, 0x8B, 0x4E, 0x18 }); };
	auto call_state = [&](std::uint32_t fn)
	{
		ld_rax(fn);
		append_call_rax(c);
	};
	auto jmp32 = [&]
	{
		c.push_back(0xE9);
		c.insert(c.end(), 4, 0);
		return c.size() - 4;
	};

	bytes({ 0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56 });
	bytes({ 0x48, 0x81, 0xEC, 0x98, 0x00, 0x00, 0x00 });
	bytes({ 0x48, 0x89, 0xCE });
	bytes({ 0x48, 0x89, 0xD3 });
	bytes({ 0x4D, 0x89, 0xC4 });
	bytes({ 0x4D, 0x89, 0xCD });
	bytes({ 0x49, 0xBE });
	append_u64(c, state);
	bytes({ 0x48, 0xC7, 0x44, 0x24, 0x40, 0x00, 0x00, 0x00, 0x00 });
	bytes({ 0x48, 0xC7, 0x44, 0x24, 0x48, 0x00, 0x00, 0x00, 0x00 });
	bytes({ 0xC7, 0x44, 0x24, 0x50, 0x00, 0x00, 0x00, 0x00 });
	bytes({ 0x48, 0xC7, 0x44, 0x24, 0x58, 0x00, 0x00, 0x00, 0x00 });
	bytes({ 0x48, 0xC7, 0x44, 0x24, 0x60, 0x00, 0x00, 0x00, 0x00 });

	std::vector<std::size_t> to_call;
	bytes({ 0x49, 0x83, 0x7E, 0x70, 0x00 });
	to_call.push_back(append_jcc32(c, 0x05));
	bytes({ 0x41, 0x83, 0x3E, 0x00 });
	to_call.push_back(append_jcc32(c, 0x04));
	bytes({ 0x41, 0x83, 0x7E, 0x08, 0x00 });
	to_call.push_back(append_jcc32(c, 0x04));
	bytes({ 0x49, 0x83, 0x7E, 0x38, 0x00 });
	to_call.push_back(append_jcc32(c, 0x04));
	bytes({ 0x41, 0x8B, 0x4E, 0x0C });
	bytes({ 0x85, 0xC9 });
	to_call.push_back(append_jcc32(c, 0x04));
	ld_rdx(offsetof(RemoteState, geoms));
	bytes({ 0x48, 0x85, 0xD2 });
	to_call.push_back(append_jcc32(c, 0x04));
	bytes({ 0x31, 0xC0 });
	const std::size_t scan = c.size();
	bytes({ 0x48, 0x39, 0x1A });
	const std::size_t j_found = append_jcc32(c, 0x04);
	bytes({ 0x48, 0x83, 0xC2, 0x38 });
	bytes({ 0xFF, 0xC0 });
	bytes({ 0x39, 0xC8 });
	patch_rel32(c, append_jcc32(c, 0x02), scan);
	to_call.push_back(jmp32());

	patch_rel32(c, j_found, c.size());
	bytes({ 0x49, 0xC7, 0x46, 0x70, 0x01, 0x00, 0x00, 0x00 });
	bytes({ 0x48, 0x89, 0x54, 0x24, 0x58 });

	ctx();
	bytes({ 0x48, 0x8D, 0x54, 0x24, 0x40 });
	bytes({ 0x45, 0x31, 0xC0, 0x45, 0x31, 0xC9 });
	call_state(offsetof(RemoteState, fn_psget));

	ctx();
	bytes({ 0x48, 0x8D, 0x54, 0x24, 0x48 });
	bytes({ 0x4C, 0x8D, 0x44, 0x24, 0x50 });
	call_state(offsetof(RemoteState, fn_dssget));

	ctx();
	bytes({ 0x48, 0x8D, 0x54, 0x24, 0x60 });
	bytes({ 0x4C, 0x8D, 0x44, 0x24, 0x68 });
	bytes({ 0x4C, 0x8D, 0x4C, 0x24, 0x78 });
	call_state(offsetof(RemoteState, fn_blendget));

	ctx();
	bytes({ 0x49, 0x8B, 0x56, 0x48 });
	bytes({ 0x45, 0x31, 0xC0, 0x45, 0x31, 0xC9 });
	bytes({ 0x48, 0x8B, 0x44, 0x24, 0x58 });
	bytes({ 0x48, 0x83, 0xC0, 0x08 });
	bytes({ 0x48, 0x89, 0x44, 0x24, 0x20 });
	bytes({ 0x48, 0xC7, 0x44, 0x24, 0x28, 0x00, 0x00, 0x00, 0x00 });
	bytes({ 0x48, 0xC7, 0x44, 0x24, 0x30, 0x00, 0x00, 0x00, 0x00 });
	call_state(offsetof(RemoteState, fn_update));

	ctx();
	bytes({ 0x49, 0x8B, 0x56, 0x38 });
	bytes({ 0x45, 0x31, 0xC0, 0x45, 0x31, 0xC9 });
	call_state(offsetof(RemoteState, fn_psset));

	ctx();
	bytes({ 0xBA, 0x0D, 0x00, 0x00, 0x00 });
	bytes({ 0x41, 0xB8, 0x01, 0x00, 0x00, 0x00 });
	bytes({ 0x4D, 0x8D, 0x4E, 0x48 });
	call_state(offsetof(RemoteState, fn_pscb));

	ctx();
	bytes({ 0x49, 0x8B, 0x56, 0x68 });
	bytes({ 0x45, 0x31, 0xC0 });
	call_state(offsetof(RemoteState, fn_dssset));

	for (std::uint8_t i = 0; i < 4; ++i)
	{
		bytes({ 0xC7, 0x84, 0x24 });
		disp32(0x80u + i * 4u);
		bytes({ 0x00, 0x00, 0x80, 0x3F });
	}
	ctx();
	bytes({ 0x49, 0x8B, 0x56, 0x58 });
	bytes({ 0x4C, 0x8D, 0x84, 0x24, 0x80, 0x00, 0x00, 0x00 });
	bytes({ 0x41, 0xB9, 0xFF, 0xFF, 0xFF, 0xFF });
	call_state(offsetof(RemoteState, fn_blendset));

	bytes({ 0x41, 0xFF, 0x86 });
	disp32(offsetof(RemoteState, draws));

	const std::size_t call_site = c.size();
	for (auto at : to_call)
		patch_rel32(c, at, call_site);

	for (std::uint8_t i = 0; i < 4; ++i)
	{
		bytes({ 0x48, 0x8B, 0x84, 0x24 });
		disp32(0xF0u + i * 8u);
		bytes({ 0x48, 0x89, 0x44, 0x24, (std::uint8_t)(0x20 + i * 8) });
	}
	bytes({ 0x48, 0x89, 0xF1 });
	bytes({ 0x48, 0x89, 0xDA });
	bytes({ 0x4D, 0x89, 0xE0 });
	bytes({ 0x4D, 0x89, 0xE9 });
	bytes({ 0x49, 0x8B, 0x46, 0x28 });
	append_call_rax(c);
	bytes({ 0x48, 0x89, 0xC7 });

	bytes({ 0x48, 0x83, 0x7C, 0x24, 0x58, 0x00 });
	const std::size_t j_out = append_jcc32(c, 0x04);

	ctx();
	bytes({ 0x48, 0x8B, 0x54, 0x24, 0x40 });
	bytes({ 0x45, 0x31, 0xC0, 0x45, 0x31, 0xC9 });
	call_state(offsetof(RemoteState, fn_psset));

	ctx();
	bytes({ 0x48, 0x8B, 0x54, 0x24, 0x48 });
	bytes({ 0x44, 0x8B, 0x44, 0x24, 0x50 });
	call_state(offsetof(RemoteState, fn_dssset));

	ctx();
	bytes({ 0x48, 0x8B, 0x54, 0x24, 0x60 });
	bytes({ 0x4C, 0x8D, 0x44, 0x24, 0x68 });
	bytes({ 0x44, 0x8B, 0x4C, 0x24, 0x78 });
	call_state(offsetof(RemoteState, fn_blendset));

	for (std::uint8_t off : { 0x40, 0x48, 0x60 })
	{
		bytes({ 0x48, 0x8B, 0x4C, 0x24, off });
		bytes({ 0x48, 0x85, 0xC9 });
		bytes({ 0x74, 0x06 });
		bytes({ 0x48, 0x8B, 0x01 });
		bytes({ 0xFF, 0x50, 0x10 });
	}

	bytes({ 0x49, 0xC7, 0x46, 0x70, 0x00, 0x00, 0x00, 0x00 });
	patch_rel32(c, j_out, c.size());
	bytes({ 0x48, 0x89, 0xF8 });
	bytes({ 0x48, 0x81, 0xC4, 0x98, 0x00, 0x00, 0x00 });
	bytes({ 0x41, 0x5E, 0x41, 0x5D, 0x41, 0x5C, 0x5F, 0x5E, 0x5B });
	c.push_back(0xC3);
	return c;
}

bool add_patch(std::uintptr_t at, std::uintptr_t thunk, std::uintptr_t* orig)
{
	if (!addr_ok(at) || !addr_ok(thunk) || g.npatch >= 16)
		return false;
	const std::uint64_t old = g_Memory.Read<std::uint64_t>(at);
	if (!old || old == thunk)
		return old == thunk;
	for (int i = 0; i < g.npatch; ++i)
	{
		if (g.patches[i].at == at)
			return true;
	}
	DWORD prot = 0;
	if (!g_Memory.Protect(at, 8, PAGE_READWRITE, &prot))
		return false;
	const bool ok = g_Memory.Write<std::uint64_t>(at, thunk);
	g_Memory.Protect(at, 8, prot, nullptr);
	if (!ok)
		return false;
	g.patches[g.npatch].at = at;
	g.patches[g.npatch].old = old;
	++g.npatch;
	if (orig && !*orig)
		*orig = (std::uintptr_t)old;
	return true;
}

void unpatch()
{
	for (int i = 0; i < g.npatch; ++i)
	{
		if (!g.patches[i].at)
			continue;
		DWORD prot = 0;
		if (g_Memory.Protect(g.patches[i].at, 8, PAGE_READWRITE, &prot))
		{
			g_Memory.Write<std::uint64_t>(g.patches[i].at, g.patches[i].old);
			g_Memory.Protect(g.patches[i].at, 8, prot, nullptr);
		}
		g.patches[i] = {};
	}
	g.npatch = 0;
}

int vt_len(std::uintptr_t vt)
{
	std::uint64_t v[k_vt_cap]{};
	if (g_Memory.ReadRaw(vt, v, sizeof(v)) != sizeof(v))
		return 0;
	int n = 0;
	for (; n < k_vt_cap; ++n)
	{
		const auto fn = (std::uintptr_t)v[n];
		if (!addr_ok(fn))
			break;
		MEMORY_BASIC_INFORMATION mbi{};
		if (!VirtualQueryEx(g_Memory.GetHandle(), (void*)fn, &mbi, sizeof(mbi))
			|| mbi.State != MEM_COMMIT || !exec_prot(mbi.Protect))
			break;
	}
	return n;
}

int clone_vt(std::uintptr_t src, std::uintptr_t dst, int slot, std::uintptr_t thunk, std::uintptr_t* orig)
{
	const int n = vt_len(src);
	if (n <= slot)
		return 0;
	const std::size_t bytes = (std::size_t)(n + 1) * 8;
	std::vector<std::uint64_t> v((std::size_t)n + 1);
	if (g_Memory.ReadRaw(src - 8, v.data(), bytes) != bytes)
		return 0;
	*orig = (std::uintptr_t)v[(std::size_t)slot + 1];
	if (!addr_ok(*orig))
		return 0;
	v[(std::size_t)slot + 1] = thunk;
	if (g_Memory.WriteRaw(dst - 8, v.data(), bytes) != bytes)
		return 0;
	return n;
}

bool patch_vtables()
{
	if (!g.present_thunk || !g.draw_thunk || !g.dc || !g.swap || !g.vt_mem)
		return false;
	const std::uintptr_t dc_vt = (std::uintptr_t)g_Memory.Read<std::uint64_t>(g.dc);
	const std::uintptr_t swap_vt = (std::uintptr_t)g_Memory.Read<std::uint64_t>(g.swap);
	if (!addr_ok(dc_vt) || !addr_ok(swap_vt) || dc_vt == g.dc_vt || swap_vt == g.swap_vt)
		return false;
	g.swap_vt = g.vt_mem + 8;
	g.dc_vt = g.vt_mem + 0x1000 + 8;
	g.nswvt = clone_vt(swap_vt, g.swap_vt, k_slot_present, g.present_thunk, &g.orig_present);
	g.ndcvt = clone_vt(dc_vt, g.dc_vt, k_slot_dc_draw, g.draw_thunk, &g.orig_draw);
	if (!g.nswvt || !g.ndcvt)
		return false;
	g_Memory.Write<std::uint64_t>(g.state + offsetof(RemoteState, orig_present), g.orig_present);
	g_Memory.Write<std::uint64_t>(g.state + offsetof(RemoteState, orig_draw), g.orig_draw);
	if (!add_patch(g.swap, g.swap_vt, nullptr))
		return false;
	return add_patch(g.dc, g.dc_vt, nullptr);
}



bool setup_meta()
{
	if (!g.device || !g.state || !g.ctx || !g.dc)
		return false;
	std::vector<std::uint8_t> ps;
	if (!compile("ps_main", "ps_5_0", ps))
		return false;
	if (g.ps_dxbc)
	{
		g_Memory.Free(g.ps_dxbc);
		g.ps_dxbc = 0;
	}
	g.ps_dxbc = g_Memory.Alloc(ps.size() + 16, PAGE_READWRITE);
	if (!g.ps_dxbc)
		return false;
	if (g_Memory.WriteRaw(g.ps_dxbc, ps.data(), ps.size()) != ps.size())
		return false;
	g.ps_len = ps.size();

	if (!g.geoms)
		g.geoms = g_Memory.Alloc((std::size_t)k_max_targets * sizeof(Target) * 2 + 16, PAGE_READWRITE);
	if (!g.geoms)
		return false;

	RemoteState st{};
	g_Memory.ReadRaw(g.state, &st, sizeof(st));
	st.device = g.device;
	st.ctx = g.ctx;
	st.dc = g.dc;
	st.geoms = 0;
	st.ngeom = 0;
	st.fn_create_ps = vt_fn(g.device, k_slot_create_ps);
	st.fn_create_buf = vt_fn(g.device, k_slot_create_buf);
	st.fn_create_dss = vt_fn(g.device, k_slot_create_dss);
	st.fn_psset = vt_fn(g.ctx, k_slot_psset);
	st.fn_psget = vt_fn(g.ctx, k_slot_psget);
	st.fn_pscb = vt_fn(g.ctx, k_slot_pscb);
	st.fn_dssset = vt_fn(g.ctx, k_slot_dssset);
	st.fn_dssget = vt_fn(g.ctx, k_slot_dssget);
	st.fn_blendset = vt_fn(g.ctx, k_slot_blendset);
	st.fn_blendget = vt_fn(g.ctx, k_slot_blendget);
	st.fn_create_blend = vt_fn(g.device, k_slot_create_blend);
	st.fn_update = vt_fn(g.ctx, k_slot_update);
	if (!addr_ok((std::uintptr_t)st.fn_create_ps) || !addr_ok((std::uintptr_t)st.fn_create_dss) ||
		!addr_ok((std::uintptr_t)st.fn_create_buf) || !addr_ok((std::uintptr_t)st.fn_psset) ||
		!addr_ok((std::uintptr_t)st.fn_psget) || !addr_ok((std::uintptr_t)st.fn_pscb) ||
		!addr_ok((std::uintptr_t)st.fn_dssset) || !addr_ok((std::uintptr_t)st.fn_dssget) ||
		!addr_ok((std::uintptr_t)st.fn_blendset) || !addr_ok((std::uintptr_t)st.fn_blendget) ||
		!addr_ok((std::uintptr_t)st.fn_create_blend) || !addr_ok((std::uintptr_t)st.fn_update))
		return false;
	st.busy = 0;
	st.cmd = 0;
	st.ready = 0;
	g_Memory.WriteRaw(g.state, &st, sizeof(st));
	return true;
}

void issue_cmd(std::uint32_t cmd, std::uintptr_t code, std::size_t len, std::uintptr_t init)
{
	g_Memory.Write<std::uint64_t>(g.state + offsetof(RemoteState, out_res), 0);
	g_Memory.Write<std::uint64_t>(g.state + offsetof(RemoteState, bytecode), code);
	g_Memory.Write<std::uint64_t>(g.state + offsetof(RemoteState, bytecode_len), len);
	g_Memory.Write<std::uint64_t>(g.state + offsetof(RemoteState, init_sys), init);
	g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, cmd), cmd);
	g.cmd_wait = true;
}

void issue_desc_cmd(std::uint32_t cmd, const void* desc, std::size_t n, std::uintptr_t init)
{
	g_Memory.WriteRaw(g.state + 0x200, desc, n);
	issue_cmd(cmd, 0, 0, init);
}

std::uint64_t take_out()
{
	const std::uint32_t cmd = g_Memory.Read<std::uint32_t>(g.state + offsetof(RemoteState, cmd));
	if (cmd)
		return 0;
	g.cmd_wait = false;
	return g_Memory.Read<std::uint64_t>(g.state + offsetof(RemoteState, out_res));
}

void store_res(std::uint64_t off, std::uint64_t v)
{
	g_Memory.Write<std::uint64_t>(g.state + off, v);
}

bool pump_creates()
{
	if (!g.state)
		return false;
	if (g.cmd_wait)
	{
		const std::uint64_t out = take_out();
		if (g.cmd_wait)
			return false;
		if (!out)
		{
			fail("create");
			g.stage = 0;
			return false;
		}
		switch (g.stage)
		{
		case 1: store_res(offsetof(RemoteState, ps), out); g.stage = 2; break;
		case 2:
			store_res(offsetof(RemoteState, dss), out);
			g.stage = 3;
			break;
		case 3: store_res(offsetof(RemoteState, cb), out); g.stage = 4; break;
		case 4:
			store_res(offsetof(RemoteState, blend), out);
			g.stage = 11;
			g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, ready), 1);
			break;
		default:
			break;
		}
	}
	if (g.cmd_wait)
		return g.stage >= 11;

	if (g.stage == 0)
	{
		g.stage = 1;
		issue_cmd(k_cmd_ps, g.ps_dxbc, g.ps_len, 0);
		return false;
	}
	if (g.stage == 2)
	{
		D3D11_DEPTH_STENCIL_DESC d{};
		d.DepthEnable = TRUE;
		d.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ALL;
		d.DepthFunc = g.depth_rev ? D3D11_COMPARISON_GREATER_EQUAL : D3D11_COMPARISON_LESS_EQUAL;
		d.StencilEnable = FALSE;
		issue_desc_cmd(k_cmd_dss, &d, sizeof(d), 0);
		return false;
	}
	if (g.stage == 3)
	{
		D3D11_BUFFER_DESC d{};
		d.ByteWidth = 48;
		d.Usage = D3D11_USAGE_DEFAULT;
		d.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
		issue_desc_cmd(k_cmd_buf, &d, sizeof(d), 0);
		return false;
	}
	if (g.stage == 4)
	{
		D3D11_BLEND_DESC d{};
		auto& rt = d.RenderTarget[0];
		rt.BlendEnable = TRUE;
		rt.SrcBlend = D3D11_BLEND_SRC_ALPHA;
		rt.DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
		rt.BlendOp = D3D11_BLEND_OP_ADD;
		rt.SrcBlendAlpha = D3D11_BLEND_ONE;
		rt.DestBlendAlpha = D3D11_BLEND_INV_SRC_ALPHA;
		rt.BlendOpAlpha = D3D11_BLEND_OP_ADD;
		rt.RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
		issue_desc_cmd(k_cmd_blend, &d, sizeof(d), 0);
		return false;
	}
	return g.stage >= 11;
}









bool Active()
{
	if (!layout::native_render)
		return false;
	for (int v : layout::native_targets)
		if (v)
			return true;
	return false;
}

bool Pick(const players::Entity& e, std::uint64_t local, bool pf, std::uint64_t pf_team)
{
	const bool is_local = e.address == local || e.is_local;
	const bool teammate = !is_local && lists::FriendlyVisual(e,
		layout::misc_teamcheck && (
			pf ? games::phantomforces::IsTeammate(e, pf_team) : players::IsTeammate(e)));
	const std::size_t idx = is_local ? 2 : (teammate ? 1 : 0);
	return idx < layout::native_targets.size() && layout::native_targets[idx];
}




bool is_vt(std::uint64_t obj, std::uint64_t rva)
{
	if (!addr_ok((std::uintptr_t)obj) || (obj & 7) || !g.module)
		return false;
	return g_Memory.Read<std::uint64_t>(obj) == g.module + rva;
}

void add_geom(std::uint64_t q, std::vector<std::uint64_t>& out)
{
	if (!is_vt(q, Offsets::GeometryD3D11::VTableRva))
		return;
	if (std::find(out.begin(), out.end(), q) == out.end())
		out.push_back(q);
}

std::uint64_t resolve_cluster(std::uint64_t node)
{
	if (is_vt(node, Offsets::FastClusterBinding::VTableRva))
	{
		++g.nbind;
		node = g_Memory.Read<std::uint64_t>(node + Offsets::FastClusterBinding::Owner)
			+ Offsets::FastCluster::BindingSubobject;
	}
	if (is_vt(node, Offsets::FastCluster::VTableRva))
		node += Offsets::FastCluster::BindingSubobject;
	return is_vt(node, Offsets::FastCluster::VTableRvaSub) ? node : 0;
}

void collect_cluster(std::uint64_t cluster, std::vector<std::uint64_t>& out)
{
	if (g.nent >= k_ent_budget)
		return;
	const std::uint64_t base = cluster - Offsets::FastCluster::BindingSubobject;
	const std::uint64_t begin =
		g_Memory.Read<std::uint64_t>(base + Offsets::FastCluster::EntityBegin);
	const std::uint64_t end =
		g_Memory.Read<std::uint64_t>(base + Offsets::FastCluster::EntityEnd);
	if (!addr_ok((std::uintptr_t)begin) || end <= begin || ((end - begin) & 7))
		return;
	if ((end - begin) > k_max_ents * 8ull)
	{
		++g.ndrop;
		return;
	}
	const int n = (int)((end - begin) / 8);
	g.nent += n;
	std::uint64_t ents[k_max_ents]{};
	if (g_Memory.ReadRaw(begin, ents, (std::size_t)n * 8) != (std::size_t)n * 8)
		return;
	for (int i = 0; i < n; ++i)
	{
		if (!addr_ok((std::uintptr_t)ents[i]) || (ents[i] & 7))
			continue;
		std::uint64_t hdr[10]{};
		if (g_Memory.ReadRaw(ents[i], hdr, sizeof(hdr)) != sizeof(hdr))
			continue;
		if (hdr[0] != g.module + Offsets::FastClusterEntity::VTableRva)
			continue;
		add_geom(hdr[Offsets::FastClusterEntity::MaterialPtr / 8], out);
		add_geom(hdr[Offsets::FastClusterEntity::DecalMaterialPtr / 8], out);
	}
}

void fill_geoms()
{
	if (!g.state || !g.geoms || g.stage < 11)
		return;

	auto off = [&]
	{
		g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, enabled), 0);
		g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, ngeom), 0);
		g.ntarget = 0;
	};

	if (!Active())
	{
		off();
		return;
	}
	auto snap = players::Snapshot();
	if (!snap)
	{
		off();
		return;
	}

	const bool pf = players::IsPhantomForces();
	const std::uint64_t pf_team = pf ? games::phantomforces::LocalTeamFolder() : 0;
	const std::uint64_t local = game::local_player.load(std::memory_order_relaxed);
	const float dscale = 0.052f;
	const float dbias = g.depth_rev ? 1.f - dscale : 0.f;
	static const auto t0 = std::chrono::steady_clock::now();
	const float now_s = std::chrono::duration<float>(std::chrono::steady_clock::now() - t0).count();

	std::vector<Target> targets;
	targets.reserve(64);
	std::vector<std::uint64_t> seen;
	seen.reserve(32);
	std::vector<std::uint64_t> taken;
	taken.reserve(64);
	g.nnode = 0;
	g.nent = 0;
	g.ndrop = 0;
	g.nbind = 0;
	g_nunk = 0;
	g_nfc = 0;
	g_npick = 0;
	g_unk_vt = 0;
	int mode = layout::native_render_shader;
	if (mode < 0) mode = 0;
	if (mode >= ShaderNameCount()) mode = ShaderNameCount() - 1;
	for (const auto& e : *snap)
	{
		if (!Pick(e, local, pf, pf_team))
			continue;
		++g_npick;
		if (e.health <= 0.f && e.max_health > 0.f)
			continue;
		if (!e.character)
			continue;
		auto baked = MeshChams::Baked(e.character);
		if (!baked)
			continue;
		for (const auto& b : *baked)
		{
			const std::uint64_t node =
				g_Memory.Read<std::uint64_t>(b.part + Offsets::BasePart::ClusterNode);
			if (std::find(seen.begin(), seen.end(), node) != seen.end())
				continue;
			seen.push_back(node);
			if (is_vt(node, Offsets::FastCluster::VTableRva)
				|| is_vt(node, Offsets::FastCluster::VTableRvaSub))
				++g_nfc;
			else if (!is_vt(node, Offsets::FastClusterBinding::VTableRva))
			{
				++g_nunk;
				if (!g_unk_vt)
					g_unk_vt = g_Memory.Read<std::uint64_t>(node);
			}
			const std::uint64_t cluster = resolve_cluster(node);
			if (!cluster)
				continue;
			++g.nnode;
			std::vector<std::uint64_t> geoms;
			collect_cluster(cluster, geoms);
			for (std::uint64_t q : geoms)
			{
				if ((int)targets.size() >= k_max_targets)
					break;
				if (std::find(taken.begin(), taken.end(), q) != taken.end())
					continue;
				taken.push_back(q);
				Target t{};
				t.geom = q;
				std::memcpy(t.color, layout::native_render_col, sizeof(t.color));
				t.glow[0] = layout::native_glow_col[0];
				t.glow[1] = layout::native_glow_col[1];
				t.glow[2] = layout::native_glow_col[2];
				t.glow[3] = layout::native_glow ? layout::native_glow_strength : 0.f;
				t.mode = mode;
				t.time = now_s;
				t.depth_scale = dscale;
				t.depth_bias = dbias;
				targets.push_back(t);
			}
		}
	}

	g.ntarget = (int)targets.size();
	if (targets.empty())
	{
		off();
		return;
	}
	const std::uintptr_t dst = g.geoms + (std::size_t)g.slot * k_max_targets * sizeof(Target);
	g_Memory.WriteRaw(dst, targets.data(), targets.size() * sizeof(Target));
	g_Memory.Write<std::uint64_t>(g.state + offsetof(RemoteState, geoms), dst);
	g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, ngeom), (std::uint32_t)targets.size());
	g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, enabled), 1);
	g.slot ^= 1;
}

bool install()
{
	if (g.hooked)
		return true;
	const auto now = std::chrono::steady_clock::now();
	if (g_fail.time_since_epoch().count() != 0 &&
		now - g_fail < std::chrono::milliseconds(800))
		return false;
	const std::uintptr_t base = module_base();
	if (!base || !g_Memory.GetHandle() || !g_Memory.IsAlive())
	{
		g_fail = now;
		return false;
	}
	if (!g.state)
		g.state = g_Memory.Alloc(0x1000, PAGE_READWRITE);
	if (!g.state)
	{
		fail("alloc");
		g_fail = now;
		return false;
	}
	if (!find_d3d())
	{
		fail("no device");
		g_fail = now;
		return false;
	}
	if (!g.ctx)
	{
		fail("no ctx");
		g_fail = now;
		return false;
	}
	if (!setup_meta())
	{
		fail("gpu meta");
		g_fail = now;
		return false;
	}

	auto cr = make_create_stub(g.state);
	auto dr = make_draw_thunk(g.state);
	auto ps = make_present_thunk(g.state, 0x10000);
	if (cr.empty() || dr.empty() || ps.empty())
	{
		fail("thunk");
		g_fail = now;
		return false;
	}
	const auto align16 = [](std::size_t n) { return (n + 15u) & ~std::size_t(15); };
	const std::size_t nps = align16(ps.size());
	const std::size_t ncr = align16(cr.size());
	const std::size_t ndr = align16(dr.size());
	const std::size_t nall = nps + ncr + ndr;
	const std::uintptr_t cave = find_dll_cave(nall, 0);
	if (!cave)
	{
		fail("cave");
		g_fail = now;
		return false;
	}
	g.cave = cave;
	g.cave_n = nall;
	g.present_thunk = cave;
	g.create_stub = cave + nps;
	g.draw_thunk = cave + nps + ncr;
	if (!g.vt_mem)
		g.vt_mem = g_Memory.Alloc(0x2000, PAGE_READWRITE);
	if (!g.vt_mem)
	{
		fail("alloc vt");
		g.cave = 0;
		g_fail = now;
		return false;
	}
	ps = make_present_thunk(g.state, g.create_stub);
	if (ps.size() > nps)
	{
		fail("thunk jmp");
		g.cave = 0;
		g_fail = now;
		return false;
	}
	if (!write_exec(g.create_stub, cr.data(), cr.size())
		|| !write_exec(g.draw_thunk, dr.data(), dr.size())
		|| !write_exec(g.present_thunk, ps.data(), ps.size()))
	{
		fail("write stub");
		g.cave = 0;
		g_fail = now;
		return false;
	}
	FlushInstructionCache(g_Memory.GetHandle(), (void*)g.cave, nall);
	mark_cfg(g.present_thunk);
	mark_cfg(g.create_stub);
	mark_cfg(g.draw_thunk);
	if (!patch_vtables())
	{
		fail("vt");
		unpatch();
		g.cave = 0;
		g_fail = now;
		return false;
	}
	g.module = base;
	g.hooked = true;
	g.stage = 0;
	if (!g.logged)
	{
		g.logged = true;
		console::Log(console::Color::Green, "nativechams on patches=%d cave=0x%llX swapvt=%d dcvt=%d swap=0x%llX dc=0x%llX",
			g.npatch, (unsigned long long)g.cave, g.nswvt, g.ndcvt,
			(unsigned long long)g.swap, (unsigned long long)g.dc);
	}
	return true;
}

void apply_occlusion(bool off)
{
	if (off == g.occl_off || !g.module)
		return;
	const std::uintptr_t flag = g.module + Offsets::FFlag::RenderFastClusterOcclusionCulling;
	if (off)
	{
		g.occl = g_Memory.Read<std::uint8_t>(flag);
		g_Memory.Write<std::uint8_t>(flag, 0);
	}
	else
		g_Memory.Write<std::uint8_t>(flag, g.occl);
	g.occl_off = off;
}

void teardown()
{
	if (g.state)
		g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, enabled), 0);
	if (!g.hooked)
		return;
	apply_occlusion(false);
	unpatch();
	g.hooked = false;
}

struct HlStyle
{
	float fill[3];
	float line[3];
	float ft;
	float ot;
	std::int32_t thick;
	std::int32_t depth;
};

struct HlRec
{
	std::uint64_t inst = 0;
	std::uint64_t character = 0;
	HlStyle style{};
};

std::unordered_map<std::uint64_t, HlRec> g_hl;

bool hl_ok(std::uint64_t p)
{
	return p >= 0x10000 && p < 0x7FFFFFFFFFFFull && g_Memory.IsValid(p);
}

HlStyle hl_now()
{
	HlStyle s{};
	std::memcpy(s.fill, layout::highlight_fill, sizeof(s.fill));
	std::memcpy(s.line, layout::highlight_outline, sizeof(s.line));
	s.ft = layout::highlight_fill_trans;
	s.ot = layout::highlight_outline_trans;
	s.thick = (std::int32_t)(layout::highlight_thickness + (layout::highlight_thickness >= 0.f ? 0.5f : -0.5f));
	s.depth = layout::highlight_depth ? 1 : 0;
	return s;
}

std::uint64_t hl_folder()
{
	const auto lp = game::local_player.load(std::memory_order_relaxed);
	if (hl_ok(lp))
	{
		const auto pg = rbx::Instance(lp).FindFirstChildOfClass("PlayerGui");
		if (pg.Valid())
			return pg.address;
	}
	const auto dm = game::data_model.load(std::memory_order_relaxed);
	if (hl_ok(dm))
	{
		const auto cg = rbx::Instance(dm).FindFirstChildOfClass("CoreGui");
		if (cg.Valid())
			return cg.address;
	}
	return 0;
}

bool hl_aimed(std::uint64_t inst, std::uint64_t ch)
{
	if (!hl_ok(inst) || !hl_ok(ch))
		return false;
	const auto parent = g_Memory.Read<std::uint64_t>(inst + Offsets::Instance::Parent);
	if (!hl_ok(parent))
		return false;
	const auto ad = g_Memory.Read<std::uint64_t>(inst + Offsets::Highlight::Adornee);
	return ad == ch || parent == ch;
}

void hl_adornee(std::uint64_t inst, std::uint64_t ch)
{
	const auto ctrl = Cheat::Features::InstanceCreate::Ctrl(ch);
	g_Memory.Write<std::uint64_t>(inst + Offsets::Highlight::Adornee, ch);
	g_Memory.Write<std::uint64_t>(inst + Offsets::Highlight::Adornee + 8, ctrl);
}

void hl_raise(std::uint64_t inst)
{
	using Cheat::Features::InstanceCreate::RaiseProp;
	RaiseProp(inst, "Highlight", "Adornee");
	RaiseProp(inst, "Highlight", "Enabled");
	RaiseProp(inst, "Highlight", "FillColor");
	RaiseProp(inst, "Highlight", "OutlineColor");
	RaiseProp(inst, "Highlight", "FillTransparency");
	RaiseProp(inst, "Highlight", "OutlineTransparency");
	RaiseProp(inst, "Highlight", "LineThickness");
	RaiseProp(inst, "Highlight", "DepthMode");
}

void hl_push(std::uint64_t inst)
{
	const std::uintptr_t base = runtime::ModuleBase();
	if (!base || !hl_ok(inst))
		return;
	if (!Cheat::Features::CallGate::Ready() && !Cheat::Features::CallGate::Install())
		return;
	std::uint64_t ret = 0;
	Cheat::Features::CallGate::Invoke(
		base + Offsets::Highlight::SetEnabled, inst + Offsets::Highlight::Prop, 0, 0, 0, &ret);
	g_Memory.Write<std::uint8_t>(inst + Offsets::Highlight::Enabled, 1);
	Cheat::Features::CallGate::Invoke(
		base + Offsets::Highlight::SetEnabled, inst + Offsets::Highlight::Prop, 1, 0, 0, &ret);
}

void hl_drop(std::uint64_t inst)
{
	if (!hl_ok(inst))
		return;
	const std::uint64_t parent = g_Memory.Read<std::uint64_t>(inst + Offsets::Instance::Parent);
	const std::uint8_t lockb = g_Memory.Read<std::uint8_t>(inst + Offsets::Instance::ParentLocked);
	if (!parent)
		return;
	if (lockb & 1)
		return;
	Cheat::Features::InstanceCreate::SetParent(inst, 0);
}

void hl_clear()
{
	for (auto& kv : g_hl)
		hl_drop(kv.second.inst);
	g_hl.clear();
}

void hl_write(std::uint64_t inst, const HlStyle& s)
{
	if (!hl_ok(inst))
		return;
	g_Memory.Write<std::uint8_t>(inst + Offsets::Highlight::Enabled, 1);
	g_Memory.WriteRaw(inst + Offsets::Highlight::FillColor, s.fill, 12);
	g_Memory.WriteRaw(inst + Offsets::Highlight::OutlineColor, s.line, 12);
	g_Memory.Write<float>(inst + Offsets::Highlight::FillTransparency, s.ft);
	g_Memory.Write<float>(inst + Offsets::Highlight::OutlineTransparency, s.ot);
	g_Memory.Write<std::int32_t>(inst + Offsets::Highlight::LineThickness, s.thick);
	g_Memory.Write<std::int32_t>(inst + Offsets::Highlight::DepthMode, s.depth);
}

void hl_update(std::uint64_t inst, HlStyle& cur, const HlStyle& s)
{
	const HlStyle o = cur;
	hl_write(inst, s);
	cur = s;
	using Cheat::Features::InstanceCreate::RaiseProp;
	if (std::memcmp(s.fill, o.fill, sizeof(s.fill)) != 0)
		RaiseProp(inst, "Highlight", "FillColor");
	if (std::memcmp(s.line, o.line, sizeof(s.line)) != 0)
		RaiseProp(inst, "Highlight", "OutlineColor");
	if (s.ft != o.ft)
		RaiseProp(inst, "Highlight", "FillTransparency");
	if (s.ot != o.ot)
		RaiseProp(inst, "Highlight", "OutlineTransparency");
	if (s.thick != o.thick)
		RaiseProp(inst, "Highlight", "LineThickness");
	if (s.depth != o.depth)
		RaiseProp(inst, "Highlight", "DepthMode");
}

bool hl_spawn(std::uint64_t* out, const HlStyle& st, std::uint64_t ch)
{
	*out = 0;
	const auto folder = hl_folder();
	if (!folder)
		return false;
	std::uint64_t inst = 0;
	if (!Cheat::Features::InstanceCreate::New("Highlight", folder, &inst) || !hl_ok(inst))
		return false;
	hl_write(inst, st);
	hl_adornee(inst, ch);
	hl_raise(inst);
	hl_push(inst);
	*out = inst;
	return true;
}

bool hl_want()
{
	if (!layout::highlight)
		return false;
	for (int v : layout::highlight_targets)
		if (v)
			return true;
	return false;
}

bool hl_pick(const players::Entity& e, std::uint64_t local, bool pf, std::uint64_t pf_team)
{
	const bool is_local = e.address == local || e.is_local;
	const bool teammate = !is_local && lists::FriendlyVisual(e,
		layout::misc_teamcheck && (
			pf ? games::phantomforces::IsTeammate(e, pf_team) : players::IsTeammate(e)));
	const std::size_t idx = is_local ? 2 : (teammate ? 1 : 0);
	return idx < layout::highlight_targets.size() && layout::highlight_targets[idx];
}

void tick_hl()
{
	if (!hl_want())
	{
		hl_clear();
		return;
	}
	if (!Cheat::Features::CallGate::Ready() && !Cheat::Features::CallGate::Install())
		return;
	auto snap = players::Snapshot();
	if (!snap)
		return;
	static std::chrono::steady_clock::time_point last_apply{};
	const auto now = std::chrono::steady_clock::now();
	const bool may_apply = now - last_apply >= std::chrono::milliseconds(120);
	bool applied = false;
	const HlStyle st = hl_now();
	const bool pf = players::IsPhantomForces();
	const std::uint64_t pf_team = pf ? games::phantomforces::LocalTeamFolder() : 0;
	const std::uint64_t local = game::local_player.load(std::memory_order_relaxed);
	int others = 0;
	int npick = 0;
	int nfail = 0;
	for (const auto& e : *snap)
		if (e.character && !(e.address == local || e.is_local))
			++others;
	std::unordered_map<std::uint64_t, char> seen;
	for (const auto& e : *snap)
	{
		if (!e.character || !hl_ok(e.character))
			continue;
		const bool is_local = e.address == local || e.is_local;
		if (!hl_pick(e, local, pf, pf_team) && !(is_local && others == 0))
			continue;
		++npick;
		seen[e.address] = 1;
		auto it = g_hl.find(e.address);
		if (it != g_hl.end() && it->second.character == e.character && hl_aimed(it->second.inst, e.character))
		{
			if (may_apply && std::memcmp(&st, &it->second.style, sizeof(st)) != 0)
			{
				hl_update(it->second.inst, it->second.style, st);
				applied = true;
			}
			continue;
		}
		if (it != g_hl.end())
			hl_drop(it->second.inst);
		HlRec rec{};
		rec.character = e.character;
		if (!hl_spawn(&rec.inst, st, e.character))
		{
			++nfail;
			g_hl.erase(e.address);
			continue;
		}
		rec.style = st;
		g_hl[e.address] = rec;
	}
	if (applied)
		last_apply = now;
	static std::chrono::steady_clock::time_point last_hl{};
	if (last_hl.time_since_epoch().count() == 0 || now - last_hl >= std::chrono::seconds(5))
	{
		last_hl = now;
		console::Log(console::Color::Yellow, "highlight n=%d pick=%d fail=%d create=%d",
			(int)g_hl.size(), npick, nfail, Cheat::Features::InstanceCreate::LastFail());
	}
	for (auto it = g_hl.begin(); it != g_hl.end(); )
	{
		if (seen.find(it->first) == seen.end())
		{
			hl_drop(it->second.inst);
			it = g_hl.erase(it);
		}
		else
			++it;
	}
}

}

void Tick()
{
	if (!g_Memory.IsAttached() || !g_Memory.IsAlive())
	{
		hl_clear();
		teardown();
		g.device = 0;
		g.ctx = 0;
		g.swap = 0;
		g.dc = 0;
		g.orig_present = 0;
		g.orig_draw = 0;
		return;
	}

	const std::uintptr_t base = module_base();
	if (g.module && base && g.module != base)
	{
		hl_clear();
		teardown();
		if (g.state) { g_Memory.Free(g.state); g.state = 0; }
		if (g.geoms) { g_Memory.Free(g.geoms); g.geoms = 0; }
		if (g.vt_mem) { g_Memory.Free(g.vt_mem); g.vt_mem = 0; }
		if (g.ps_dxbc) { g_Memory.Free(g.ps_dxbc); g.ps_dxbc = 0; }
		g = {};
		g_why = nullptr;
	}

	tick_hl();
	if (!Active() && !g.hooked)
		return;
	const bool rev = want_reverse();
	if (!g.hooked)
	{
		g.depth_rev = rev;
		if (!install())
			return;
		console::Log(console::Color::Yellow, "nativechams depth=%s", rev ? "reverse" : "standard");
	}
	if (g.stage >= 11 && g.depth_rev != rev)
	{
		g.depth_rev = rev;
		g.stage = 2;
		g_Memory.Write<std::uint32_t>(g.state + offsetof(RemoteState, ready), 0);
		console::Log(console::Color::Yellow, "nativechams depth=%s", rev ? "reverse" : "standard");
	}
	pump_creates();
	fill_geoms();
	apply_occlusion(layout::native_walls && g.ntarget > 0);
	static auto last_stat = std::chrono::steady_clock::time_point{};
	static int last_stage = -1;
	if (g.stage == 11 && last_stage != 11)
	{
		last_stage = 11;
		console::Log(console::Color::Green, "nativechams ready st=%d cre=%u",
			g.stage, Creates());
	}
	const auto now = std::chrono::steady_clock::now();
	if (last_stat.time_since_epoch().count() == 0 ||
		now - last_stat >= std::chrono::seconds(5))
	{
		last_stat = now;
		console::Log(console::Color::Yellow,
			"nativechams st=%d rdy=%u frames=%u draws=%u geom=%u node=%d ent=%d bind=%d drop=%d pick=%d unk=%d fc=%d",
			g.stage, Ready(), Entered(), Draws(), Items(), g.nnode, g.nent, g.nbind, g.ndrop,
			g_npick, g_nunk, g_nfc);
	}
}

void Stop()
{
	hl_clear();
	teardown();
}

void Dump()
{
	if (!g.hooked && !g.state)
		return;
	console::Crash("nativechams hooked=%d st=%d rdy=%u draws=%u geom=%u node=%d ent=%d bind=%d drop=%d",
		g.hooked ? 1 : 0, g.stage, Ready(), Draws(), Items(), g.nnode, g.nent, g.nbind, g.ndrop);
	if (!g.state)
		return;
	RemoteState st{};
	g_Memory.ReadRaw(g.state, &st, sizeof(st));
	console::Crash("nativechams ps=0x%llX dss=0x%llX cb=0x%llX blend=0x%llX entered=%u last_rtv=0x%llX",
		(unsigned long long)st.ps, (unsigned long long)st.dss,
		(unsigned long long)st.cb, (unsigned long long)st.blend,
		st.entered, (unsigned long long)st.last_rtv);
}

bool Hooked()
{
	return g.hooked;
}

const char* Why()
{
	if (g.hooked)
	return nullptr;
	return g_why ? g_why : "off";
}

std::uintptr_t Cave()
{
	return g.cave;
}

std::size_t CaveSize()
{
	return g.cave_n;
}

bool CaveBusy(std::uintptr_t at, std::size_t n)
{
	if (!at || !n)
		return false;
	return g.cave && at < g.cave + g.cave_n && g.cave < at + n;
}

std::uint32_t Draws()
{
	if (!g.state)
	return 0;
	return g_Memory.Read<std::uint32_t>(g.state + offsetof(RemoteState, draws));
}

std::uint32_t Items()
{
	if (!g.state)
	return 0;
	return g_Memory.Read<std::uint32_t>(g.state + offsetof(RemoteState, ngeom));
}

std::uint32_t Entered()
{
	if (!g.state)
		return 0;
	return g_Memory.Read<std::uint32_t>(g.state + offsetof(RemoteState, entered));
}

std::uint32_t Creates()
{
	if (!g.state)
		return 0;
	return g_Memory.Read<std::uint32_t>(g.state + offsetof(RemoteState, creates));
}

std::uint32_t Stage()
{
	return g.stage;
}

std::uint32_t Ready()
{
	if (!g.state)
		return 0;
	return g_Memory.Read<std::uint32_t>(g.state + offsetof(RemoteState, ready));
}

const char* const* ShaderNames()
{
	static const char* k[] = {
		"Flat", "Lit", "Clay", "Glass", "Crystal", "Ice", "Prism", "Heat", "Core"
	};
	return k;
}

int ShaderNameCount()
{
	return 9;
}

}
}
}

