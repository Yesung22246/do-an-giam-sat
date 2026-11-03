import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Bell,
  Check,
  Clock3,
  Globe,
  LayoutDashboard,
  Lock,
  LogOut,
  Menu,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Trash2,
  X,
  Pencil,
  Signal,
  Settings,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./style.css";
const API = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const REFRESH_MS = 30000; // tự làm mới dữ liệu mỗi 30 giây khi nối API thật

// ----- Dữ liệu DEMO (chỉ dùng khi chưa cấu hình API) -----
// Mỗi monitor mang sẵn current_status giống hệt API thật trả về, để giao diện
// demo và giao diện thật chạy CHUNG một logic (không gõ cứng theo id).
const ago = (minutes) => new Date(Date.now() - minutes * 60000).toISOString();
const seed = [
  {
    id: 1,
    name: "Shop API",
    type: "http",
    target: "https://shop.example.com",
    port: null,
    interval_seconds: 60,
    retries: 3,
    enabled: true,
    current_status: "up",
    last_checked_at: ago(0.3),
    last_response_ms: 118.4,
  },
  {
    id: 2,
    name: "Main Website",
    type: "http",
    target: "https://website.example.com",
    port: null,
    interval_seconds: 60,
    retries: 3,
    enabled: true,
    current_status: "down",
    last_checked_at: ago(0.8),
    last_response_ms: null,
    last_error: "Mã trạng thái không mong đợi: 504",
  },
  {
    id: 3,
    name: "Database Server",
    type: "tcp",
    target: "db.example.com",
    port: 5432,
    interval_seconds: 60,
    retries: 3,
    enabled: true,
    current_status: "up",
    last_checked_at: ago(0.5),
    last_response_ms: 38.2,
  },
  {
    id: 4,
    name: "SSL shop.example.com",
    type: "ssl",
    target: "shop.example.com",
    port: 443,
    interval_seconds: 300,
    retries: 3,
    enabled: true,
    current_status: "up",
    last_checked_at: ago(3),
    last_response_ms: null,
  },
  {
    id: 5,
    name: "Development SSH",
    type: "tcp",
    target: "dev.example.com",
    port: 22,
    interval_seconds: 120,
    retries: 3,
    enabled: false,
    current_status: "paused",
  },
];
const chartSeed = Array.from({ length: 24 }, (_, i) => ({
  time: `${String(i).padStart(2, "0")}:00`,
  latency: Math.round(
    105 +
      Math.sin(i * 0.7) * 28 +
      Math.cos(i * 0.33) * 15 +
      (i === 8 ? 105 : 0),
  ),
}));
const seedInc = [
  {
    id: 4,
    monitor_id: 2,
    state: "open",
    started_at: ago(6),
    resolved_at: null,
    cause: "Dịch vụ SẬP. Nguyên nhân: Mã trạng thái không mong đợi: 504",
    severity: "critical",
  },
  {
    id: 3,
    monitor_id: 1,
    state: "resolved",
    started_at: ago(60 * 14),
    resolved_at: ago(60 * 14 - 4),
    cause: "Dịch vụ chập chờn (lên/xuống liên tục).",
    severity: "warning",
  },
  {
    id: 2,
    monitor_id: 3,
    state: "resolved",
    started_at: ago(60 * 38),
    resolved_at: ago(60 * 38 - 13),
    cause: "Dịch vụ SẬP. Nguyên nhân: Không mở được cổng 5432",
    severity: "critical",
  },
];

// ----- Tiện ích hiển thị -----
const STATUS = {
  up: ["up", "Operational"],
  degraded: ["degraded", "Degraded"],
  down: ["down", "Down"],
  paused: ["paused", "Paused"],
  pending: ["pending", "Pending"],
};
const statusOf = (m) => m.current_status || (m.enabled ? "pending" : "paused");
const TYPE_ICON = { http: Globe, tcp: Server, ssl: Lock };
const INTERVALS = [10, 30, 60, 120, 300];
const PERIODS = [
  ["6", "6 giờ qua"],
  ["24", "24 giờ qua"],
  ["168", "7 ngày qua"],
  ["720", "30 ngày qua"],
];

function timeAgo(iso) {
  if (!iso) return "Chưa kiểm tra";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "Vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  return `${Math.floor(s / 86400)} ngày trước`;
}

function duration(fromIso, toIso) {
  const mins = Math.max(
    0,
    Math.round(
      ((toIso ? new Date(toIso) : new Date()) - new Date(fromIso)) / 60000,
    ),
  );
  if (mins < 60) return `${mins} phút`;
  const h = Math.floor(mins / 60);
  return mins % 60 ? `${h} giờ ${mins % 60} phút` : `${h} giờ`;
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

// Gom số lượng monitor theo trạng thái (dùng cho vòng tròn, legend, status page).
function countByStatus(monitors) {
  const c = { up: 0, degraded: 0, down: 0, paused: 0, pending: 0 };
  monitors.forEach((m) => (c[statusOf(m)] += 1));
  return c;
}

// Trạng thái tổng của hệ thống (giống overall_status bên backend).
function overallOf(monitors) {
  const active = monitors.filter((m) => statusOf(m) !== "paused");
  const c = countByStatus(active);
  if (c.down && c.down === active.length) return "down";
  if (c.down || c.degraded) return "degraded";
  return "operational";
}
const OVERALL_TEXT = {
  operational: "All systems operational",
  degraded: "Partial service disruption",
  down: "Major outage",
};

// Vòng tròn tỷ lệ trạng thái, tính từ số monitor thật (không cố định %).
function ringOf(c) {
  const total = c.up + c.degraded + c.down + c.paused + c.pending;
  if (!total) return "#e6e9f0";
  let acc = 0;
  const parts = [
    ["#46bd8a", c.up],
    ["#e0a03c", c.degraded],
    ["#ef7a7d", c.down],
    ["#e6e9f0", c.paused + c.pending],
  ]
    .filter(([, n]) => n > 0)
    .map(([color, n]) => {
      const from = (acc / total) * 100;
      acc += n;
      return `${color} ${from}% ${(acc / total) * 100}%`;
    });
  return `conic-gradient(${parts.join(", ")})`;
}

function TypeIcon({ type, size }) {
  const Icon = TYPE_ICON[type] || Globe;
  return <Icon size={size} />;
}
function App() {
  const storedToken = localStorage.getItem("pw-token") || "";
  // Đã có phiên thật từ trước -> không hiện dữ liệu demo trong lúc chờ API.
  const startLive = Boolean(API && storedToken && storedToken !== "demo-token");
  const [token, setToken] = useState(storedToken),
    [email, setEmail] = useState("admin@example.com"),
    [password, setPassword] = useState(""),
    [authMode, setAuthMode] = useState("login"),
    [authError, setAuthError] = useState("");
  const [page, setPage] = useState("dashboard"),
    [monitors, setMonitors] = useState(startLive ? [] : seed),
    [incidents, setIncidents] = useState(startLive ? [] : seedInc),
    [selectedId, setSelectedId] = useState(1),
    [period, setPeriod] = useState("24"),
    [results, setResults] = useState(startLive ? [] : chartSeed),
    [uptime, setUptime] = useState(
      startLive
        ? null
        : { uptime_percent: 99.8, avg_response_ms: 118.6, total_checks: 1440 },
    ),
    [me, setMe] = useState(null),
    [statusPage, setStatusPage] = useState(null),
    [lastSync, setLastSync] = useState(null),
    [live, setLive] = useState(false),
    [search, setSearch] = useState(""),
    [modal, setModal] = useState(""),
    [form, setForm] = useState({
      name: "",
      type: "http",
      target: "",
      port: "",
      interval_seconds: 60,
      retries: 3,
      enabled: true,
    }),
    [toast, setToast] = useState(""),
    [mobile, setMobile] = useState(false),
    [publicId, setPublicId] = useState("demo-status");
  const notify = (s) => {
    setToast(s);
    setTimeout(() => setToast(""), 2600);
  };
  async function api(path, opts = {}) {
    let r;
    try {
      r = await fetch(API + path, {
        ...opts,
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(opts.headers || {}),
        },
      });
    } catch {
      throw Error("Không kết nối được tới máy chủ API");
    }
    // Token hết hạn / không hợp lệ -> đăng xuất (trừ chính trang đăng nhập).
    if (r.status === 401 && !path.startsWith("/auth/login")) {
      logout();
      throw Error("Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại");
    }
    if (!r.ok) {
      // FastAPI trả {"detail": "..."} hoặc danh sách lỗi validate -> lấy câu dễ đọc.
      let msg = `Lỗi máy chủ (HTTP ${r.status})`;
      try {
        const j = await r.json();
        if (typeof j.detail === "string") msg = j.detail;
        else if (Array.isArray(j.detail))
          msg = j.detail.map((d) => d.msg).join("; ");
      } catch {
        /* giữ thông báo mặc định */
      }
      throw Error(msg);
    }
    if (r.status === 204) return null;
    return r.json();
  }
  async function auth(e) {
    e.preventDefault();
    setAuthError("");
    if (!API) {
      let t = "demo-token";
      setToken(t);
      localStorage.setItem("pw-token", t);
      return;
    }
    try {
      let d = await api(
        "/auth/" + (authMode === "login" ? "login" : "register"),
        { method: "POST", body: JSON.stringify({ email, password }) },
      );
      // Xóa dữ liệu demo trước khi tải dữ liệu thật của tài khoản.
      setMonitors([]);
      setIncidents([]);
      setResults([]);
      setUptime(null);
      setToken(d.token);
      localStorage.setItem("pw-token", d.token);
      setLive(true);
    } catch (err) {
      setAuthError(err.message);
    }
  }
  const isLive = Boolean(API && token && token !== "demo-token");

  // silent=true: lần tự làm mới định kỳ, không bật thông báo.
  async function sync(silent = false) {
    if (!isLive) {
      if (!silent) notify("Đang dùng dữ liệu demo");
      return;
    }
    try {
      const [list, allIncidents, user] = await Promise.all([
        api("/monitors"),
        api("/incidents"),
        api("/auth/me"), // tải lại mỗi lần: khách vừa nâng gói thì thấy ngay
      ]);
      setMonitors(list);
      setIncidents(allIncidents);
      setMe(user);
      // Trang status công khai của TV2 nhận public_id = id tài khoản.
      setPublicId((p) => (p === "demo-status" ? String(user.id) : p));
      const m = list.find((x) => x.id === selectedId) || list[0];
      if (m) {
        if (m.id !== selectedId) setSelectedId(m.id);
        const [r, u] = await Promise.all([
          api(`/monitors/${m.id}/results?hours=${period}`),
          api(`/monitors/${m.id}/uptime?hours=${period}`),
        ]);
        setResults(r);
        setUptime(u);
      } else {
        setResults([]);
        setUptime(null);
      }
      setLive(true);
      setLastSync(new Date());
      if (!silent) notify("Đã đồng bộ dữ liệu mới nhất");
    } catch (e) {
      notify("Lỗi API: " + e.message);
    }
  }
  // Nối API thật: tải ngay rồi tự làm mới mỗi 30 giây (sản phẩm giám sát phải
  // tự cập nhật, người dùng không cần bấm tay mới thấy dịch vụ sập).
  useEffect(() => {
    if (!isLive) return;
    sync(true);
    const timer = setInterval(() => sync(true), REFRESH_MS);
    return () => clearInterval(timer);
  }, [token, selectedId, period]);
  const selected = monitors.find((m) => m.id === selectedId) || monitors[0];
  const longRange = Number(period) > 24;
  const graph = useMemo(
    () =>
      results.map((r) => ({
        time:
          r.time ||
          new Date(r.checked_at).toLocaleString(
            "vi-VN",
            longRange
              ? { day: "2-digit", month: "2-digit", hour: "2-digit" }
              : { hour: "2-digit", minute: "2-digit" },
          ),
        // Lần kiểm tra lỗi không có độ trễ -> để trống (đứt nét), KHÔNG vẽ thành 0ms.
        latency:
          r.latency ??
          (r.response_time_ms == null
            ? null
            : Math.round(Number(r.response_time_ms))),
      })),
    [results, longRange],
  );
  const latencies = graph.map((g) => g.latency).filter((v) => v != null);
  const counts = countByStatus(monitors);
  const openIncidents = incidents.filter((i) => i.state === "open");
  const displayName = (me?.email || email || "user").split("@")[0];
  const initial = displayName.charAt(0).toUpperCase();
  const hasUptime = uptime && uptime.total_checks > 0;
  const periodLabel = (PERIODS.find(([v]) => v === period) || PERIODS[1])[1];
  // Chu kỳ nhanh nhất gói dịch vụ cho phép (Free 60s, Pro 30s, Business 10s).
  const minInterval = isLive ? me?.plan?.min_interval || 60 : 10;
  const filtered = monitors.filter((m) =>
    (m.name + " " + m.target + " " + m.type)
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  function openNew() {
    setForm({
      name: "",
      type: "http",
      target: "",
      port: "",
      interval_seconds: Math.max(60, minInterval),
      retries: 3,
      enabled: true,
    });
    setModal("new");
  }
  function edit(m) {
    setForm({ ...m, port: m.port ?? "" });
    setSelectedId(m.id);
    setModal("edit");
  }
  async function save(e) {
    e.preventDefault();
    // Chỉ gửi các trường người dùng được sửa (không gửi kèm current_status...).
    let data = {
      name: form.name.trim(),
      type: form.type,
      target: form.target.trim(),
      port: form.port === "" || form.port == null ? null : Number(form.port),
      interval_seconds: Number(form.interval_seconds),
      retries: Number(form.retries),
      enabled: Boolean(form.enabled),
    };
    if (data.type === "ssl" && !data.port) data.port = 443;
    try {
      if (isLive) {
        let d =
          modal === "new"
            ? await api("/monitors", {
                method: "POST",
                body: JSON.stringify(data),
              })
            : await api(`/monitors/${selectedId}`, {
                method: "PUT",
                body: JSON.stringify(data),
              });
        setMonitors((p) =>
          modal === "new"
            ? [...p, d]
            : p.map((m) => (m.id === selectedId ? d : m)),
        );
      } else if (modal === "new") {
        setMonitors((p) => [
          ...p,
          {
            ...data,
            id: Math.max(0, ...p.map((m) => m.id)) + 1,
            current_status: data.enabled ? "pending" : "paused",
          },
        ]);
      } else
        setMonitors((p) =>
          p.map((m) =>
            m.id === selectedId
              ? {
                  ...m,
                  ...data,
                  current_status: data.enabled
                    ? m.current_status === "paused"
                      ? "pending"
                      : m.current_status
                    : "paused",
                }
              : m,
          ),
        );
      setModal("");
      notify(
        modal === "new"
          ? "Đã thêm monitor — sẽ được kiểm tra trong vài giây"
          : "Đã lưu monitor",
      );
    } catch (err) {
      notify("Lưu thất bại: " + err.message);
    }
  }
  async function del(m) {
    if (!confirm(`Xóa monitor "${m.name}"?`)) return;
    try {
      if (isLive) await api(`/monitors/${m.id}`, { method: "DELETE" });
      setMonitors((p) => p.filter((x) => x.id !== m.id));
      setIncidents((p) => p.filter((i) => i.monitor_id !== m.id));
      notify("Đã xóa monitor");
    } catch (e) {
      notify(e.message);
    }
  }
  async function publicLoad(e) {
    e.preventDefault();
    if (!isLive) {
      notify("Chế độ demo — đang xem trước từ dữ liệu demo");
      return;
    }
    try {
      setStatusPage(await api(`/status/${encodeURIComponent(publicId)}`));
      notify("Đã tải trang trạng thái công khai");
    } catch (err) {
      setStatusPage(null);
      notify(err.message);
    }
  }
  function logout() {
    setToken("");
    localStorage.removeItem("pw-token");
    setLive(false);
    setMe(null);
    setStatusPage(null);
    setMonitors(seed);
    setIncidents(seedInc);
    setResults(chartSeed);
  }
  if (!token)
    return (
      <div className="auth">
        <div className="auth-side">
          <div className="brand">
            <Activity /> pulsewatch
          </div>
          <div className="hero">
            <small>● MONITORING THAT MOVES WITH YOU</small>
            <h1>
              Keep your services
              <br />
              <em>always in sight.</em>
            </h1>
            <p>
              Giám sát uptime, độ trễ và sự cố trong một dashboard trực quan.
            </p>
            <div className="stats">
              <span>
                <b>99.98%</b>
                <small>Uptime mục tiêu</small>
              </span>
              <span>
                <b>24/7</b>
                <small>Giám sát liên tục</small>
              </span>
              <span>
                <b>&lt; 1 min</b>
                <small>Chu kỳ kiểm tra</small>
              </span>
            </div>
          </div>
          <small className="copyright">
            PULSEWATCH MONITORING PLATFORM · TV3 FRONTEND
          </small>
        </div>
        <div className="auth-main">
          <form className="auth-form" onSubmit={auth}>
            <div className="lock">▣</div>
            <h2>
              {authMode === "login" ? "Chào mừng trở lại" : "Tạo tài khoản mới"}
            </h2>
            <p>Đăng nhập để quản lý hệ thống monitor của bạn.</p>
            <label>Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label>Mật khẩu</label>
            <input
              type="password"
              required
              minLength={4}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Ít nhất 4 ký tự"
            />
            {authError && <div className="error">{authError}</div>}
            <button className="primary wide">
              {authMode === "login" ? "Đăng nhập" : "Đăng ký"}{" "}
              <ArrowUpRight size={16} />
            </button>
            <div className="switch">
              {authMode === "login" ? "Chưa có tài khoản?" : "Đã có tài khoản?"}{" "}
              <button
                type="button"
                onClick={() =>
                  setAuthMode(authMode === "login" ? "register" : "login")
                }
              >
                {authMode === "login" ? "Đăng ký" : "Đăng nhập"}
              </button>
            </div>
            {!API && (
              <div className="demo">
                ⚡ Chế độ demo — chưa cấu hình API backend.
              </div>
            )}
          </form>
          <small className="terms">
            Bằng việc tiếp tục, bạn đồng ý với Điều khoản dịch vụ và Chính sách
            bảo mật.
          </small>
        </div>
      </div>
    );
  return (
    <div className="shell">
      <aside className={"sidebar " + (mobile ? "show" : "")}>
        <div className="brand">
          <Activity /> pulsewatch <small>BETA</small>
        </div>
        <label className="navlabel">WORKSPACE</label>
        {[
          ["dashboard", LayoutDashboard, "Overview"],
          ["monitors", Globe, "Monitors"],
          ["incidents", AlertTriangle, "Incidents"],
          ["status", Signal, "Status page"],
          ["settings", Settings, "Settings"],
        ].map(([id, Icon, label]) => (
          <button
            key={id}
            className={"nav " + (page === id ? "active" : "")}
            onClick={() => {
              setPage(id);
              setMobile(false);
            }}
          >
            <Icon size={18} />
            {label}
            {id === "monitors" && <span>{monitors.length}</span>}
            {id === "incidents" && openIncidents.length > 0 && (
              <span title="Sự cố đang mở">{openIncidents.length}</span>
            )}
          </button>
        ))}
        <div className="sidebottom">
          <div className="help">
            <b> Cần trợ giúp?</b>
            <small>Xem hướng dẫn sử dụng</small>
          </div>
          <div className="profile">
            <div className="avatar">{initial}</div>
            <span>
              <b>{displayName}</b>
              <small>
                {!isLive
                  ? "Demo workspace"
                  : me?.role === "admin"
                    ? "Quản trị viên"
                    : `Gói ${me?.plan?.name || "Free"}`}
              </small>
            </span>
            <button title="Đăng xuất" onClick={logout}>
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      {mobile && <div className="scrim" onClick={() => setMobile(false)} />}
      <main className="main">
        <header className="topbar">
          <button className="hamb" onClick={() => setMobile(!mobile)}>
            <Menu />
          </button>
          <div className="crumb">
            Workspace <span>/</span>{" "}
            <b>
              {page === "dashboard"
                ? "Overview"
                : page[0].toUpperCase() + page.slice(1)}
            </b>
          </div>
          <div className="topactions">
            <span
              className={"pill " + (isLive && live ? "green" : "")}
              title={
                lastSync
                  ? "Cập nhật lúc " + lastSync.toLocaleTimeString("vi-VN")
                  : ""
              }
            >
              <i /> {isLive && live ? "Live · tự cập nhật 30s" : "Demo mode"}
            </span>
            <button
              className="iconbutton"
              onClick={() => sync()}
              title="Đồng bộ ngay"
            >
              <RefreshCw size={17} />
            </button>
            <button
              className="iconbutton"
              title="Sự cố đang mở"
              onClick={() =>
                openIncidents.length
                  ? setPage("incidents")
                  : notify("Không có sự cố nào đang mở")
              }
            >
              <Bell size={18} />
            </button>
            <div className="avatar">{initial}</div>
          </div>
        </header>
        <div className="content">
          {page === "dashboard" && (
            <>
              <div className="heading">
                <div>
                  <small className="eyebrow">● SYSTEM OVERVIEW</small>
                  <h1>
                    {greeting()}, {displayName} ✦
                  </h1>
                  <p>
                    Đây là tình trạng tổng quan của các dịch vụ bạn đang giám
                    sát.
                  </p>
                </div>
                <button className="primary" onClick={openNew}>
                  <Plus size={16} /> Add monitor
                </button>
              </div>
              <div className="metrics">
                <Metric
                  icon={<Globe />}
                  label="Total monitors"
                  value={monitors.length}
                  note={
                    monitors.length
                      ? `${counts.up} hoạt động tốt · ${counts.down + counts.degraded} có vấn đề`
                      : "Chưa có monitor nào"
                  }
                  tone="blue"
                />
                <Metric
                  icon={<ShieldCheck />}
                  label={`Uptime · ${periodLabel}`}
                  value={hasUptime ? `${uptime.uptime_percent}%` : "—"}
                  note={
                    selected
                      ? hasUptime
                        ? `${selected.name} · ${uptime.total_checks} lần kiểm tra`
                        : `${selected.name} · chưa có dữ liệu`
                      : "Chưa có monitor nào"
                  }
                  tone="green"
                />
                <Metric
                  icon={<Activity />}
                  label="Avg. response time"
                  value={
                    hasUptime && uptime.avg_response_ms != null
                      ? `${Number(uptime.avg_response_ms).toFixed(1)} ms`
                      : "—"
                  }
                  note={selected ? `${selected.name} · ${periodLabel}` : "—"}
                  tone="purple"
                />
                <Metric
                  icon={<AlertTriangle />}
                  label="Open incidents"
                  value={openIncidents.length}
                  note={
                    openIncidents.length
                      ? `${openIncidents.length} sự cố cần xử lý`
                      : "Không có sự cố nào đang mở"
                  }
                  tone="orange"
                />
              </div>
              <div className="twocol">
                <section className="panel">
                  <div className="panelhead">
                    <div>
                      <h3>Response time</h3>
                      <p>Độ trễ trung bình theo thời gian</p>
                    </div>
                    <div className="filters">
                      <select
                        value={selectedId}
                        onChange={(e) => setSelectedId(Number(e.target.value))}
                      >
                        {monitors.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                      </select>
                      <select
                        value={period}
                        onChange={(e) => setPeriod(e.target.value)}
                      >
                        {PERIODS.map(([v, label]) => (
                          <option key={v} value={v}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="chartlegend">
                    <span>
                      🔵 Latency{" "}
                      <b>
                        {hasUptime && uptime.avg_response_ms != null
                          ? `${Number(uptime.avg_response_ms).toFixed(0)} ms avg.`
                          : "—"}
                      </b>
                    </span>
                    <small>
                      {isLive ? "● Live monitoring" : "● Demo data"}
                    </small>
                  </div>
                  <div className="chart">
                    {latencies.length === 0 ? (
                      <div className="chartempty">
                        <div>
                          <b>Chưa có dữ liệu độ trễ</b>
                          {selected
                            ? selected.type === "ssl"
                              ? "Monitor SSL chỉ kiểm tra hạn chứng chỉ, không đo độ trễ."
                              : "Hệ thống sẽ vẽ biểu đồ sau vài lần kiểm tra đầu tiên."
                            : "Thêm monitor đầu tiên để bắt đầu giám sát."}
                        </div>
                      </div>
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart
                          data={graph}
                          margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                        >
                          <defs>
                            <linearGradient
                              id="fill"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="0%"
                                stopColor="#6479f3"
                                stopOpacity={0.25}
                              />
                              <stop
                                offset="100%"
                                stopColor="#6479f3"
                                stopOpacity={0}
                              />
                            </linearGradient>
                          </defs>
                          <CartesianGrid
                            strokeDasharray="3 5"
                            vertical={false}
                            stroke="#edf0f6"
                          />
                          <XAxis
                            dataKey="time"
                            tick={{ fontSize: 10, fill: "#929bad" }}
                            axisLine={false}
                            tickLine={false}
                            interval="preserveStartEnd"
                            minTickGap={28}
                          />
                          <YAxis
                            tick={{ fontSize: 10, fill: "#929bad" }}
                            axisLine={false}
                            tickLine={false}
                            tickFormatter={(v) => v + "ms"}
                          />
                          <Tooltip formatter={(v) => [v + " ms", "Latency"]} />
                          <Area
                            dataKey="latency"
                            type="monotone"
                            stroke="#6479f3"
                            strokeWidth={2.5}
                            fill="url(#fill)"
                            connectNulls={false}
                            isAnimationActive={!isLive}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                  <div className="chartfoot">
                    <span>
                      Minimum{" "}
                      <b>
                        {latencies.length
                          ? `${Math.min(...latencies)} ms`
                          : "—"}
                      </b>
                    </span>
                    <span>
                      Average{" "}
                      <b>
                        {hasUptime && uptime.avg_response_ms != null
                          ? `${Number(uptime.avg_response_ms).toFixed(1)} ms`
                          : "—"}
                      </b>
                    </span>
                    <span>
                      Maximum{" "}
                      <b>
                        {latencies.length
                          ? `${Math.max(...latencies)} ms`
                          : "—"}
                      </b>
                    </span>
                  </div>
                </section>
                <section className="panel">
                  <div className="panelhead">
                    <div>
                      <h3>Monitor status</h3>
                      <p>Trạng thái tất cả dịch vụ</p>
                    </div>
                    <button
                      className="link"
                      onClick={() => setPage("monitors")}
                    >
                      View all ↗
                    </button>
                  </div>
                  <div className="statussummary">
                    <div
                      className="ring"
                      style={{ background: ringOf(counts) }}
                    >
                      <b>{monitors.length}</b>
                      <small>Monitors</small>
                    </div>
                    <div className="legend">
                      <span>
                        🟢 Operational <b>{counts.up}</b>
                      </span>
                      <span>
                        🟡 Degraded <b>{counts.degraded}</b>
                      </span>
                      <span>
                        🔴 Down <b>{counts.down}</b>
                      </span>
                      <span>
                        ⚪ Paused / pending{" "}
                        <b>{counts.paused + counts.pending}</b>
                      </span>
                    </div>
                  </div>
                  {[...monitors]
                    // Dịch vụ đang có vấn đề được đưa lên đầu.
                    .sort(
                      (a, b) =>
                        ["down", "degraded", "pending", "up", "paused"].indexOf(
                          statusOf(a),
                        ) -
                        ["down", "degraded", "pending", "up", "paused"].indexOf(
                          statusOf(b),
                        ),
                    )
                    .slice(0, 4)
                    .map((m) => (
                      <div className="statusrow" key={m.id}>
                        <span className="serviceicon">
                          <TypeIcon type={m.type} size={16} />
                        </span>
                        <span className="servicename">
                          <b>{m.name}</b>
                          <small>{m.target}</small>
                        </span>
                        <Status m={m} />
                      </div>
                    ))}
                </section>
              </div>
              <section className="panel tablepanel">
                <div className="panelhead">
                  <div>
                    <h3>Your monitors</h3>
                    <p>The latest health checks from your services</p>
                  </div>
                  <button className="link" onClick={() => setPage("monitors")}>
                    Manage monitors ↗
                  </button>
                </div>
                <MonitorTable
                  monitors={monitors.slice(0, 4)}
                  edit={edit}
                  del={del}
                />
              </section>
              <section className="panel">
                <div className="panelhead">
                  <div>
                    <h3>Recent incidents</h3>
                    <p>Những sự cố gần đây nhất</p>
                  </div>
                  <button className="link" onClick={() => setPage("incidents")}>
                    All incidents ↗
                  </button>
                </div>
                <Incidents
                  incidents={incidents.slice(0, 3)}
                  monitors={monitors}
                />
              </section>
            </>
          )}
          {page === "monitors" && (
            <>
              <div className="heading">
                <div>
                  <small className="eyebrow">SERVICE MANAGEMENT</small>
                  <h1>Monitors</h1>
                  <p>Quản lý và theo dõi tất cả endpoint của bạn.</p>
                </div>
                <button className="primary" onClick={openNew}>
                  <Plus size={16} /> Add monitor
                </button>
              </div>
              <section className="panel">
                <div className="toolbar">
                  <div className="search">
                    <Search size={16} />
                    <input
                      placeholder="Tìm theo tên, URL..."
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </div>
                  <span>{filtered.length} monitors</span>
                </div>
                <MonitorTable monitors={filtered} edit={edit} del={del} />
              </section>
            </>
          )}
          {page === "incidents" && (
            <>
              <div className="heading">
                <div>
                  <small className="eyebrow">EVENT TIMELINE</small>
                  <h1>Incidents</h1>
                  <p>
                    Lịch sử sự cố của các dịch vụ bạn đang giám sát
                    {openIncidents.length
                      ? ` — ${openIncidents.length} sự cố đang mở.`
                      : "."}
                  </p>
                </div>
              </div>
              <section className="panel">
                <Incidents incidents={incidents} monitors={monitors} />
              </section>
            </>
          )}
          {page === "status" && (
            <>
              <div className="heading">
                <div>
                  <small className="eyebrow">PUBLIC TRANSPARENCY</small>
                  <h1>Status page</h1>
                  <p>Trang trạng thái công khai dành cho khách hàng.</p>
                </div>
              </div>
              <section className="panel public">
                <div className="publicbrand">
                  <Activity />
                  <div>
                    <h2>PulseWatch Status</h2>
                    <p>Real-time service status and incident communication</p>
                  </div>
                </div>
                {(() => {
                  // Có dữ liệu tải từ API công khai thì dùng, chưa có thì xem
                  // trước từ chính danh sách monitor (cùng một cách tính).
                  const rows = statusPage
                    ? statusPage.monitors.map((m) => ({
                        ...m,
                        enabled: true,
                      }))
                    : monitors.filter((m) => statusOf(m) !== "paused");
                  const overall = statusPage
                    ? statusPage.overall_status
                    : overallOf(monitors);
                  return (
                    <>
                      <div className={"allgood " + overall}>
                        {overall === "operational" ? (
                          <Check />
                        ) : (
                          <AlertTriangle />
                        )}
                        <b>{OVERALL_TEXT[overall] || overall}</b>
                        <small>
                          {statusPage
                            ? `Public ID ${statusPage.public_id}`
                            : "Xem trước"}
                        </small>
                      </div>
                      <h3>Services</h3>
                      {rows.map((m) => (
                        <div className="publicrow" key={m.id}>
                          <span>
                            <b>{m.name}</b>
                            <small>
                              {m.target}
                              {m.uptime_percent_24h != null &&
                                ` · uptime 24h ${m.uptime_percent_24h}%`}
                            </small>
                          </span>
                          <Status m={m} />
                        </div>
                      ))}
                      {!rows.length && (
                        <div className="empty">
                          Chưa có dịch vụ nào để công khai.
                        </div>
                      )}
                    </>
                  );
                })()}
                <form className="publicform" onSubmit={publicLoad}>
                  <label>Public ID</label>
                  <input
                    value={publicId}
                    onChange={(e) => setPublicId(e.target.value)}
                  />
                  <button className="primary">
                    Tải status từ API <ArrowUpRight size={15} />
                  </button>
                </form>
                <small className="muted">
                  Khách hàng của bạn xem trang này qua API công khai GET
                  /status/
                  {"{public_id}"} (không cần đăng nhập). Public ID mặc định là
                  mã tài khoản của bạn{me ? ` (${me.id})` : ""}.
                </small>
              </section>
            </>
          )}
          {page === "settings" && (
            <>
              <div className="heading">
                <div>
                  <small className="eyebrow">PREFERENCES</small>
                  <h1>Settings</h1>
                  <p>Cấu hình kết nối và phiên đăng nhập.</p>
                </div>
              </div>
              <section className="panel settings">
                <h3>API connection</h3>
                <p>Địa chỉ backend được đặt trong biến môi trường frontend.</p>
                <div className="setting">
                  <span>API Base URL</span>
                  <code>{API || "Chưa đặt — đang dùng mock data"}</code>
                </div>
                <div className="setting">
                  <span>Authentication</span>
                  <code>
                    {token === "demo-token" ? "Demo token" : "JWT token stored"}
                  </code>
                </div>
                <button className="primary" onClick={sync}>
                  <RefreshCw size={15} /> Test / sync API
                </button>
                <button className="secondary" onClick={logout}>
                  <LogOut size={15} /> Đăng xuất
                </button>
              </section>
            </>
          )}
        </div>
        <footer>
          © 2026 PulseWatch{" "}
          <span>
            ● {OVERALL_TEXT[overallOf(monitors)]}
            {lastSync
              ? ` · cập nhật ${lastSync.toLocaleTimeString("vi-VN")}`
              : ""}
          </span>
        </footer>
      </main>
      {modal && (
        <div className="backdrop" onClick={() => setModal("")}>
          <form
            className="modal"
            onSubmit={save}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modalhead">
              <div>
                <h2>{modal === "new" ? "Add new monitor" : "Edit monitor"}</h2>
                <p>Cấu hình endpoint cần theo dõi.</p>
              </div>
              <button
                type="button"
                className="iconbutton"
                onClick={() => setModal("")}
              >
                <X />
              </button>
            </div>
            <label>Monitor name</label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Main Website"
            />
            <label>Monitor type</label>
            <select
              value={form.type}
              onChange={(e) => {
                const type = e.target.value;
                setForm({
                  ...form,
                  type,
                  port:
                    type === "http"
                      ? ""
                      : type === "ssl"
                        ? form.port || 443
                        : form.port,
                });
              }}
            >
              <option value="http">HTTP / HTTPS — website, API</option>
              <option value="tcp">TCP port — database, SSH...</option>
              <option value="ssl">
                SSL certificate — cảnh báo sắp hết hạn
              </option>
            </select>
            <label>{form.type === "http" ? "Target URL" : "Hostname"}</label>
            <input
              required
              value={form.target}
              onChange={(e) => setForm({ ...form, target: e.target.value })}
              placeholder={
                form.type === "http"
                  ? "https://example.com"
                  : form.type === "ssl"
                    ? "example.com (không có https://)"
                    : "server.example.com"
              }
            />
            {form.type !== "http" && (
              <>
                <label>Port</label>
                <input
                  type="number"
                  required={form.type === "tcp"}
                  min="1"
                  max="65535"
                  value={form.port}
                  placeholder={form.type === "ssl" ? "443" : "5432"}
                  onChange={(e) => setForm({ ...form, port: e.target.value })}
                />
              </>
            )}
            <div className="formrow">
              <div>
                <label>Interval</label>
                <select
                  value={form.interval_seconds}
                  onChange={(e) =>
                    setForm({ ...form, interval_seconds: e.target.value })
                  }
                >
                  {INTERVALS.filter((s) => s >= minInterval).map((s) => (
                    <option key={s} value={s}>
                      {s < 60 ? `${s} seconds` : `${s / 60} minute${s > 60 ? "s" : ""}`}
                    </option>
                  ))}
                </select>
                {minInterval > 10 && isLive && (
                  <small className="muted">
                    Gói {me?.plan?.name}: tối thiểu {minInterval}s
                  </small>
                )}
              </div>
              <div>
                <label>Retries</label>
                <select
                  value={form.retries}
                  onChange={(e) =>
                    setForm({ ...form, retries: e.target.value })
                  }
                >
                  <option value="1">1 retry</option>
                  <option value="3">3 retries</option>
                  <option value="5">5 retries</option>
                </select>
              </div>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) =>
                  setForm({ ...form, enabled: e.target.checked })
                }
              />{" "}
              Enable monitoring immediately
            </label>
            <div className="modalactions">
              <button
                type="button"
                className="secondary"
                onClick={() => setModal("")}
              >
                Cancel
              </button>
              <button className="primary">
                <Check size={15} /> Save monitor
              </button>
            </div>
          </form>
        </div>
      )}
      {toast && (
        <div className="toast">
          <Check size={16} />
          {toast}
        </div>
      )}
    </div>
  );
}
function Metric({ icon, label, value, note, tone }) {
  return (
    <div className="metric">
      <div className={"metricicon " + tone}>{icon}</div>
      <small>{label}</small>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}
// Trạng thái lấy từ current_status do backend tính theo Alert Engine (TV1).
function Status({ m }) {
  const [cls, label] = STATUS[statusOf(m)] || STATUS.pending;
  return (
    <span className={"status " + cls} title={m.last_error || ""}>
      <i />
      {label}
    </span>
  );
}
function MonitorTable({ monitors, edit, del }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th>MONITOR</th>
            <th>STATUS</th>
            <th>TYPE</th>
            <th>INTERVAL</th>
            <th>LAST CHECK</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {monitors.map((m) => (
            <tr key={m.id}>
              <td>
                <div className="monitorname">
                  <span>
                    <TypeIcon type={m.type} size={17} />
                  </span>
                  <div>
                    <b>{m.name}</b>
                    <small>
                      {m.target}
                      {m.port ? ":" + m.port : ""}
                    </small>
                  </div>
                </div>
              </td>
              <td>
                <Status m={m} />
              </td>
              <td>
                <code>{m.type.toUpperCase()}</code>
              </td>
              <td>
                <span className="interval">
                  <Clock3 size={13} />
                  {m.interval_seconds}s
                </span>
              </td>
              <td>
                <span
                  className={"last " + statusOf(m)}
                  title={m.last_error || ""}
                >
                  <i />{" "}
                  {statusOf(m) === "paused"
                    ? "Đã tạm dừng"
                    : timeAgo(m.last_checked_at)}
                  {m.last_response_ms != null &&
                    ` · ${Math.round(m.last_response_ms)} ms`}
                </span>
              </td>
              <td>
                <button
                  className="smallicon"
                  title="Sửa"
                  onClick={() => edit(m)}
                >
                  <Pencil size={14} />
                </button>
                <button
                  className="smallicon"
                  title="Xóa"
                  onClick={() => del(m)}
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!monitors.length && (
        <div className="empty">Không tìm thấy monitor nào.</div>
      )}
    </div>
  );
}
function Incidents({ incidents, monitors }) {
  return (
    <div className="incidentlist">
      {incidents.map((i) => {
        let m = monitors.find((x) => x.id === i.monitor_id);
        return (
          <div className="incident" key={i.id}>
            <span className={"incidenticon " + i.severity}>
              <AlertTriangle size={17} />
            </span>
            <div className="incidentbody">
              <div>
                <b>{m?.name || `Monitor #${i.monitor_id}`}</b>{" "}
                <span className={"severity " + i.severity}>{i.severity}</span>{" "}
                {i.state === "open" ? (
                  <span className="resolved ongoing">● Đang diễn ra</span>
                ) : (
                  <span className="resolved">
                    <Check size={12} /> Resolved
                  </span>
                )}
              </div>
              <p>{i.cause}</p>
              <small>
                <Clock3 size={12} />{" "}
                {new Date(i.started_at).toLocaleString("vi-VN")} ·{" "}
                {i.state === "open"
                  ? `đã kéo dài ${duration(i.started_at)}`
                  : `kéo dài ${duration(i.started_at, i.resolved_at)}`}
              </small>
            </div>
          </div>
        );
      })}
      {!incidents.length && <div className="empty">Chưa có sự cố nào.</div>}
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
