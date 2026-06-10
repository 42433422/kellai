import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  useAuthStore,
  getRememberedEmails,
  getLastEmail,
  forgetEmail,
  getSavedCredential,
  saveCredential,
  setAutoLoginEnabled,
  clearSavedCredential,
  deobfuscatePassword,
  type RememberedAccount,
} from "../stores/auth";
import { clsx } from "clsx";
import {
  Mail,
  Phone,
  Lock,
  User,
  Eye,
  EyeOff,
  ArrowRight,
  ChevronDown,
  X,
  KeyRound,
  Check,
} from "lucide-react";

/* ============ 通用：复选框 ============ */

interface CheckboxProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  children?: React.ReactNode;
}

function Checkbox({
  checked,
  onChange,
  disabled,
  ariaLabel,
  className,
  children,
}: CheckboxProps) {
  return (
    <label
      className={clsx(
        "inline-flex select-none items-center gap-1.5 text-sm",
        disabled ? "cursor-not-allowed" : "cursor-pointer",
        className
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only peer"
      />
      <span
        aria-hidden="true"
        className={clsx(
          "relative flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors duration-150",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-blue-500/30 peer-focus-visible:ring-offset-1",
          disabled
            ? "border-gray-200 bg-gray-100"
            : checked
            ? "border-blue-600 bg-blue-600"
            : "border-gray-300 bg-white peer-hover:border-blue-400"
        )}
      >
        {checked && <Check className="h-3 w-3 stroke-[3] text-white" />}
      </span>
      {children && (
        <span
          className={clsx(
            "text-sm",
            disabled ? "text-gray-400" : "text-gray-700"
          )}
        >
          {children}
        </span>
      )}
    </label>
  );
}

/* ============ 通用：表单输入字段 ============ */

interface FormFieldProps {
  label: string;
  icon: React.ReactNode;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  error?: string;
  placeholder?: string;
  maxLength?: number;
  autoFocus?: boolean;
  inputRef?: React.RefObject<HTMLInputElement>;
  /** 右侧附加元素（如密码可见切换按钮） */
  rightSlot?: React.ReactNode;
  /** 覆盖外层 className */
  className?: string;
}

function FormField({
  label,
  icon,
  value,
  onChange,
  type = "text",
  error,
  placeholder,
  maxLength,
  autoFocus,
  inputRef,
  rightSlot,
  className,
}: FormFieldProps) {
  return (
    <div className={className}>
      <label className="mb-1.5 block text-sm font-medium text-gray-700">
        {label}
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center text-gray-400 [&>svg]:h-4 [&>svg]:w-4">
          {icon}
        </span>
        <input
          ref={inputRef}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          maxLength={maxLength}
          autoFocus={autoFocus}
          className={clsx(
            // 不用 text-black/纯黑，用偏柔的深色，既"明显"又不刺眼。
            // placeholder 用更淡的灰（gray-400）拉开和 value 的视觉对比。
            "w-full rounded-lg border py-2.5 pl-10 text-sm text-slate-700 outline-none transition-colors focus:ring-2 placeholder:text-gray-300 focus:placeholder:text-gray-200",
            rightSlot ? "pr-10" : "pr-4",
            error
              ? "border-red-300 focus:border-red-500 focus:ring-red-500/20"
              : "border-gray-300 focus:border-blue-500 focus:ring-blue-500/20"
          )}
        />
        {rightSlot && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            {rightSlot}
          </div>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
    </div>
  );
}

/* ============ 通用：密码可见切换按钮 ============ */

function PasswordToggle({
  visible,
  onChange,
}: {
  visible: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      aria-label={visible ? "隐藏密码" : "显示密码"}
      onClick={() => onChange(!visible)}
      className="flex h-4 w-4 items-center justify-center text-gray-400 hover:text-gray-600"
    >
      {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
    </button>
  );
}

/* ============ 通用：渐变头像圆圈 ============ */

function AvatarBadge({
  char,
  active = false,
  size = "md",
}: {
  char: string;
  active?: boolean;
  size?: "sm" | "md";
}) {
  return (
    <div
      className={clsx(
        "flex shrink-0 items-center justify-center rounded-full font-semibold text-white",
        size === "sm" ? "h-7 w-7 text-xs" : "h-8 w-8 text-sm",
        active
          ? "bg-gradient-to-br from-blue-500 to-indigo-600"
          : "bg-gradient-to-br from-gray-400 to-gray-500"
      )}
    >
      {char}
    </div>
  );
}

/* ============ 纯函数：校验 & 头像字符 ============ */

const isValidEmail = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
const isValidPhone = (v: string) => /^1[3-9]\d{9}$/.test(v);
const isPasswordLongEnough = (v: string) => v.length >= 6;

/** 取首字符做头像。用 Array.from 处理 surrogate pair（emoji、CJK 扩展 B 等）。 */
function avatarChar(label: string): string {
  const s = (label || "").trim();
  if (!s) return "?";
  const first = Array.from(s)[0] || "";
  return first.toUpperCase();
}

/* ============ 主组件 ============ */

type LoginTab = "email" | "phone";
type AuthMode = "login" | "register";

export default function Login() {
  const [tab, setTab] = useState<LoginTab>("email");
  const [mode, setMode] = useState<AuthMode>("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // 邮箱登录表单
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // 记忆账号
  const [remembered, setRemembered] = useState<RememberedAccount[]>([]);
  const [activeEmail, setActiveEmail] = useState<string>("");
  const [showAccountPicker, setShowAccountPicker] = useState(false);
  const [showEmailInput, setShowEmailInput] = useState(false);
  /**
   * "切换账号"前那个 activeEmail 缓存。点"返回"时一键回切。
   * 仅在 useAnotherAccount 触发后被设置，回到原账号后清空。
   */
  const [lastActiveEmail, setLastActiveEmail] = useState<string>("");

  // 记住密码 + 7 天免登录
  const [rememberPassword, setRememberPassword] = useState(true);
  const [autoLogin7Days, setAutoLogin7Days] = useState(true);
  /** 当前 activeEmail 是否有已保存的密码凭据（决定是否能显示"直接进入"） */
  const [hasSavedPassword, setHasSavedPassword] = useState(false);

  // 手机号登录表单
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [countdown, setCountdown] = useState(0);

  // 注册表单
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regConfirmPassword, setRegConfirmPassword] = useState("");
  const [regName, setRegName] = useState("");

  // 表单验证错误
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const passwordRef = useRef<HTMLInputElement>(null);
  /** setTimeout handle，用于在卸载/重复触发时清理 */
  const focusTimerRef = useRef<number | null>(null);
  /** 避免"邮箱输入到一半焦点被偷"：只有显式调用 focusPasswordSoon 才聚焦。 */
  const initialFocusDoneRef = useRef(false);

  const { login, loginBySms, register } = useAuthStore();
  const navigate = useNavigate();

  /* ====== 工具：清空错误状态 ====== */
  const clearMessages = useCallback(() => {
    setError("");
    setFieldErrors({});
  }, []);

  const clearFieldError = useCallback((field: string) => {
    setFieldErrors((prev) => {
      const { [field]: _drop, ...rest } = prev;
      return rest;
    });
  }, []);

  /* ====== 工具：延迟聚焦密码框（带 cleanup） ====== */
  const focusPasswordSoon = useCallback(() => {
    if (focusTimerRef.current !== null) {
      window.clearTimeout(focusTimerRef.current);
    }
    focusTimerRef.current = window.setTimeout(() => {
      focusTimerRef.current = null;
      passwordRef.current?.focus();
    }, 50);
  }, []);

  /* ====== 初始加载：读记忆账号 / 决定 activeEmail / 一次性聚焦 ====== */
  useEffect(() => {
    const list = getRememberedEmails();
    setRemembered(list);
    if (list.length === 0) {
      setShowEmailInput(true);
      return;
    }
    const last = getLastEmail();
    if (last) {
      setActiveEmail(last);
      setEmail(last);
      setShowEmailInput(false);
      // 一次性聚焦密码框；不放在 activeEmail 的 effect 里，避免输入邮箱时被偷焦点
      if (!initialFocusDoneRef.current) {
        initialFocusDoneRef.current = true;
        focusPasswordSoon();
      }
    } else {
      setShowEmailInput(true);
    }
    // 仅首次挂载执行
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ====== 组件卸载时清理定时器 ====== */
  useEffect(() => {
    return () => {
      if (focusTimerRef.current !== null) {
        window.clearTimeout(focusTimerRef.current);
        focusTimerRef.current = null;
      }
    };
  }, []);

  /* ====== 已登录用户：直接重定向到首页，不让输密码 ====== */
  useEffect(() => {
    if (useAuthStore.getState().isAuthenticated) {
      navigate("/", { replace: true });
    }
  }, [navigate]);

  /* ====== activeEmail 变化 → 检查凭据（不触发聚焦） ====== */
  useEffect(() => {
    if (!activeEmail) {
      setHasSavedPassword(false);
      return;
    }
    const cred = getSavedCredential(activeEmail);
    setHasSavedPassword(!!cred);
    setAutoLogin7Days(cred?.autoLoginEnabled ?? true);
  }, [activeEmail]);

  /* ====== 验证码倒计时 ====== */
  useEffect(() => {
    if (countdown <= 0) return;
    const timer = window.setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown]);

  /* ====== 通用：跑一个异步动作并自动管理 loading/error ====== */
  const run = useCallback(
    async (fn: () => Promise<void>, fallbackMsg: string) => {
      setError("");
      setLoading(true);
      try {
        await fn();
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : fallbackMsg;
        setError(message);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /* ====== 校验函数（合并重复逻辑） ====== */

  const validateEmailLogin = () => {
    const errors: Record<string, string> = {};
    if (!email) errors.email = "请输入邮箱";
    else if (!isValidEmail(email)) errors.email = "邮箱格式不正确";
    if (!password) errors.password = "请输入密码";
    else if (!isPasswordLongEnough(password))
      errors.password = "密码至少 6 位";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const validatePhoneLogin = () => {
    const errors: Record<string, string> = {};
    if (!phone) errors.phone = "请输入手机号";
    else if (!isValidPhone(phone)) errors.phone = "手机号格式不正确";
    if (!code) errors.code = "请输入验证码";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const validateRegister = () => {
    const errors: Record<string, string> = {};
    if (!regEmail) errors.regEmail = "请输入邮箱";
    else if (!isValidEmail(regEmail)) errors.regEmail = "邮箱格式不正确";
    if (!regPassword) errors.regPassword = "请输入密码";
    else if (!isPasswordLongEnough(regPassword))
      errors.regPassword = "密码至少 6 位";
    if (!regConfirmPassword) errors.regConfirmPassword = "请确认密码";
    else if (regPassword !== regConfirmPassword)
      errors.regConfirmPassword = "两次密码不一致";
    if (!regName) errors.regName = "请输入显示名称";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  /* ====== 提交：邮箱登录 ====== */

  /**
   * 核心登录：保存密码（受 rememberPassword 控制；凭 autoLogin 决定是否 7 天免登录）
   * displayName 从 auth store 的 user 状态读取，保证头像/记忆 chip 有真实昵称。
   */
  const performLogin = async (
    loginEmail: string,
    loginPassword: string
  ) => {
    await login(loginEmail, loginPassword);
    if (rememberPassword) {
      const u = useAuthStore.getState().user;
      const displayName = u?.display_name || u?.name || "";
      saveCredential(loginEmail, loginPassword, displayName, autoLogin7Days);
    }
    setRemembered(getRememberedEmails());
  };

  const handleEmailLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateEmailLogin()) return;
    void run(async () => {
      await performLogin(email, password);
      navigate("/");
    }, "登录失败，请检查账号密码");
  };

  /** 一键进入：用已保存的密码登录 */
  const handleQuickLogin = () => {
    if (!activeEmail) return;
    void run(async () => {
      const cred = getSavedCredential(activeEmail);
      if (!cred) throw new Error("该账号没有已保存的密码");
      const pwd = deobfuscatePassword(cred.password);
      if (!pwd) {
        clearSavedCredential(activeEmail);
        setHasSavedPassword(false);
        throw new Error("保存的密码已损坏，请重新输入");
      }
      setPassword(pwd);
      await performLogin(activeEmail, pwd);
      navigate("/");
    }, "登录失败，请检查账号密码");
  };

  /* ====== 提交：手机号登录 ====== */
  const handlePhoneLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validatePhoneLogin()) return;
    void run(async () => {
      await loginBySms(phone, code);
      // 同步预填手机号到 localStorage，下次进入可恢复
      try {
        localStorage.setItem("kellai_last_phone", phone);
      } catch {
        /* noop */
      }
      navigate("/");
    }, "登录失败，请检查验证码");
  };

  /* ====== 提交：注册 ====== */
  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateRegister()) return;
    void run(async () => {
      await register({
        email: regEmail,
        password: regPassword,
        name: regName,
      });
      // 注册成功：保存凭据（默认勾选"记住密码"）
      if (rememberPassword) {
        saveCredential(regEmail, regPassword, regName, autoLogin7Days);
      }
      setMode("login");
      setTab("email");
      setActiveEmail(regEmail);
      setEmail(regEmail);
      setPassword("");
      setError("");
      setLastActiveEmail("");
      setRemembered(getRememberedEmails());
    }, "注册失败，请稍后重试");
  };

  /* ====== 切模式 / 切 tab ====== */
  const switchMode = (newMode: AuthMode) => {
    setMode(newMode);
    if (newMode === "login") {
      setPassword("");
    } else {
      // 进注册时清掉所有登录相关的临时状态，避免回切时残留
      setActiveEmail("");
      setEmail("");
      setPassword("");
      setHasSavedPassword(false);
      setLastActiveEmail("");
    }
    clearMessages();
  };

  const switchTab = (newTab: LoginTab) => {
    setTab(newTab);
    clearMessages();
  };

  /* ====== 切账号 / 移除账号 ====== */
  const pickAccount = (acc: RememberedAccount) => {
    setActiveEmail(acc.email);
    setEmail(acc.email);
    setPassword("");
    setShowAccountPicker(false);
    setShowEmailInput(false);
    setLastActiveEmail(""); // 选了账号后清掉"返回"目标
    clearMessages();
    focusPasswordSoon();
  };

  const removeAccount = (acc: RememberedAccount, e?: React.MouseEvent) => {
    e?.stopPropagation();
    forgetEmail(acc.email);
    clearSavedCredential(acc.email); // 同步清掉凭据
    const next = getRememberedEmails();
    setRemembered(next);
    if (activeEmail.toLowerCase() === acc.email.toLowerCase()) {
      const newLast = next[0]?.email || "";
      setActiveEmail(newLast);
      setEmail(newLast);
      setHasSavedPassword(false);
      if (!newLast) setShowEmailInput(true);
    }
  };

  const useAnotherAccount = () => {
    // 记住"切换前"那个 activeEmail，让"返回"按钮能一键回切
    if (activeEmail) setLastActiveEmail(activeEmail);
    setActiveEmail("");
    setEmail("");
    setPassword("");
    setShowEmailInput(true);
    setHasSavedPassword(false);
    clearMessages();
  };

  /** 从"切换账号"模式回到上一个账号 */
  const revertToLastActive = () => {
    if (!lastActiveEmail) return;
    const target = lastActiveEmail;
    setActiveEmail(target);
    setEmail(target);
    setPassword("");
    setShowEmailInput(false);
    setHasSavedPassword(false);
    setLastActiveEmail("");
    clearMessages();
    focusPasswordSoon();
  };

  /* ====== 渲染：记忆账号 chip ====== */
  const renderRememberedChip = () => {
    if (!activeEmail) return null;
    const acc = remembered.find(
      (x) => x.email.toLowerCase() === activeEmail.toLowerCase()
    );
    const display = acc?.displayName || activeEmail;
    return (
      <div className="mb-4 flex items-center justify-between rounded-lg border border-blue-100 bg-blue-50/60 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <AvatarBadge char={avatarChar(display)} />
          <div className="min-w-0">
            {acc?.displayName && (
              <div className="truncate text-sm font-medium text-gray-900">
                {acc.displayName}
              </div>
            )}
            <div className="truncate text-xs text-gray-500">{activeEmail}</div>
          </div>
        </div>
        <button
          type="button"
          onClick={useAnotherAccount}
          className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-100 hover:text-blue-700"
        >
          切换账号
        </button>
      </div>
    );
  };

  /* ====== 渲染：账号选择器 ====== */
  const renderAccountPicker = () => {
    // 过滤掉当前 active 账号：它已经在 chip 里显示了，不该在 picker 里再列一次
    const others = remembered.filter(
      (x) => x.email.toLowerCase() !== activeEmail.toLowerCase()
    );
    if (others.length < 1) return null;
    return (
      <div className="relative mb-4">
        <button
          type="button"
          onClick={() => setShowAccountPicker((s) => !s)}
          className="flex w-full items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 hover:border-gray-300 hover:bg-gray-50"
        >
          <span className="flex items-center gap-2">
            <User className="h-3.5 w-3.5 text-gray-400" />
            {activeEmail ? "切换到其他已登录账号" : "使用其他已登录账号"}
          </span>
          <ChevronDown
            className={clsx(
              "h-4 w-4 text-gray-400 transition-transform",
              showAccountPicker && "rotate-180"
            )}
          />
        </button>
        {showAccountPicker && (
          <div className="absolute left-0 right-0 z-10 mt-1 max-h-64 overflow-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
            {others.map((acc) => {
              const isActive = false; // 已被过滤掉，这里不会触发
              return (
                <div
                  key={acc.email}
                  className="group flex cursor-pointer items-center gap-2.5 px-3 py-2 hover:bg-gray-50"
                  onClick={() => pickAccount(acc)}
                >
                  <AvatarBadge
                    char={avatarChar(acc.displayName || acc.email)}
                    active={isActive}
                    size="sm"
                  />
                  <div className="min-w-0 flex-1">
                    {acc.displayName && (
                      <div className="truncate text-sm font-medium text-gray-900">
                        {acc.displayName}
                      </div>
                    )}
                    <div className="truncate text-xs text-gray-500">
                      {acc.email}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => removeAccount(acc, e)}
                    className="rounded p-1 text-gray-300 opacity-0 hover:bg-gray-200 hover:text-gray-600 group-hover:opacity-100"
                    title="从记忆列表移除"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  /* ====== 渲染：邮箱登录用的"记住密码 + 7 天免登录"区 ====== */
  const renderEmailRememberOptions = () => (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-sm">
        <button
          type="button"
          onClick={() => {
            // TODO: 接入后端 /api/kellai/auth/forgot 后跳转到对应流程
            setError("忘记密码流程暂未上线，请联系管理员重置。");
          }}
          className="text-blue-600 transition-colors hover:text-blue-700 hover:underline"
        >
          忘记密码？
        </button>
        <div className="flex items-center gap-4">
          <Checkbox
            checked={rememberPassword}
            ariaLabel="记住密码"
            onChange={(v: boolean) => {
              setRememberPassword(v);
              // 关掉"记住密码"时联动关掉"7天免登录"
              if (!v) {
                setAutoLogin7Days(false);
                if (activeEmail) setAutoLoginEnabled(activeEmail, false);
              }
            }}
          >
            记住密码
          </Checkbox>
          <Checkbox
            checked={autoLogin7Days}
            ariaLabel="7 天免登录"
            onChange={(v: boolean) => {
              setAutoLogin7Days(v);
              if (activeEmail) setAutoLoginEnabled(activeEmail, v);
            }}
          >
            7 天免登录
          </Checkbox>
        </div>
      </div>
      {hasSavedPassword && activeEmail && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => {
              clearSavedCredential(activeEmail);
              setHasSavedPassword(false);
              setAutoLogin7Days(false);
            }}
            className="text-xs text-gray-400 transition-colors hover:text-red-500"
          >
            清除此账号保存的密码
          </button>
        </div>
      )}
    </div>
  );

  /* ====== 渲染：注册用的"记住密码"区（无 7 天免登录/忘记密码/清除等无关项） ====== */
  const renderRegisterRememberOptions = () => (
    <Checkbox
      checked={rememberPassword}
      ariaLabel="记住密码"
      onChange={setRememberPassword}
    >
      记住密码
    </Checkbox>
  );

  return (
    <div className="flex h-screen">
      {/* 左侧品牌区域 */}
      <div className="relative hidden w-[480px] shrink-0 flex-col items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800 lg:flex">
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute -left-20 -top-20 h-72 w-72 rounded-full bg-blue-500/10 blur-3xl" />
          <div className="absolute -bottom-20 -right-20 h-72 w-72 rounded-full bg-indigo-500/10 blur-3xl" />
          <div className="absolute left-1/2 top-1/3 h-48 w-48 -translate-x-1/2 rounded-full bg-cyan-500/5 blur-2xl" />
        </div>

        <div className="relative z-10 flex flex-col items-center px-12 text-center">
          <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-500/25">
            <span className="text-2xl font-bold text-white">客</span>
          </div>
          <h1 className="mb-3 text-4xl font-bold tracking-tight text-white">
            客来来
          </h1>
          <p className="text-lg text-slate-300">AI 驱动的智能获客助手</p>
          <div className="mt-8 space-y-3 text-sm text-slate-400">
            <div className="flex items-center gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/20">
                <ArrowRight className="h-3 w-3 text-blue-400" />
              </div>
              <span>智能客户线索自动获取</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-500/20">
                <ArrowRight className="h-3 w-3 text-indigo-400" />
              </div>
              <span>AI 对话提升转化效率</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/20">
                <ArrowRight className="h-3 w-3 text-cyan-400" />
              </div>
              <span>全渠道客户关系管理</span>
            </div>
          </div>
        </div>

        <p className="absolute bottom-6 text-xs text-slate-500">
          © 2024 客来来 All rights reserved.
        </p>
      </div>

      {/* 右侧表单区域 */}
      <div className="flex flex-1 items-center justify-center bg-gray-50 px-6">
        <div className="w-full max-w-[420px]">
          <div className="mb-8 text-center lg:hidden">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600">
              <span className="text-lg font-bold text-white">客</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">客来来</h1>
            <p className="mt-1 text-sm text-gray-500">AI 驱动的智能获客助手</p>
          </div>

          <div className="mb-6">
            <h2 className="text-2xl font-bold text-gray-900">
              {mode === "login" ? "欢迎回来" : "创建账号"}
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              {mode === "login"
                ? "登录您的账号以继续使用"
                : "注册一个新账号开始使用"}
            </p>
          </div>

          {mode === "login" && (
            <div className="mb-6 flex rounded-lg bg-gray-100 p-1">
              <button
                onClick={() => switchTab("email")}
                className={clsx(
                  "flex flex-1 items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors",
                  tab === "email"
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                )}
              >
                <Mail className="h-4 w-4" />
                邮箱登录
              </button>
              <button
                onClick={() => switchTab("phone")}
                className={clsx(
                  "flex flex-1 items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors",
                  tab === "phone"
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                )}
              >
                <Phone className="h-4 w-4" />
                手机号登录
              </button>
            </div>
          )}

          {error && (
            <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-600">
              {error}
            </div>
          )}

          {/* 邮箱登录表单 */}
          {mode === "login" && tab === "email" && (
            <form onSubmit={handleEmailLogin} className="space-y-4">
              {renderAccountPicker()}
              {renderRememberedChip()}

              {showEmailInput && (
                <>
                  {lastActiveEmail &&
                    lastActiveEmail.toLowerCase() !==
                      activeEmail.toLowerCase() && (
                      <button
                        type="button"
                        onClick={revertToLastActive}
                        className="mb-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600 transition-colors hover:text-blue-700"
                      >
                        <ArrowRight className="h-3 w-3 rotate-180" />
                        返回上一账号（{lastActiveEmail}）
                      </button>
                    )}
                  <FormField
                    label="邮箱"
                    icon={<Mail className="h-4 w-4" />}
                    type="email"
                    value={email}
                    onChange={(v) => {
                      setEmail(v);
                      clearFieldError("email");
                      // 邮箱变化时切换 activeEmail，触发凭据检查（但不主动 focus）
                      const trimmed = v.trim().toLowerCase();
                      if (
                        trimmed &&
                        isValidEmail(trimmed) &&
                        trimmed !== activeEmail
                      ) {
                        setActiveEmail(trimmed);
                      }
                    }}
                    placeholder="请输入邮箱"
                    autoFocus
                    error={fieldErrors.email}
                  />
                </>
              )}

              <FormField
                label="密码"
                icon={<Lock className="h-4 w-4" />}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(v) => {
                  setPassword(v);
                  clearFieldError("password");
                }}
                placeholder={
                  hasSavedPassword
                    ? "已为您保存密码，直接点登录"
                    : "请输入密码"
                }
                autoFocus={!showEmailInput && !!activeEmail}
                inputRef={passwordRef}
                error={fieldErrors.password}
                rightSlot={
                  <PasswordToggle
                    visible={showPassword}
                    onChange={setShowPassword}
                  />
                }
              />

              {renderEmailRememberOptions()}

              {/* 主按钮：有已保存密码 → 只显示"一键进入"；没保存 → 显示"登录" */}
              {hasSavedPassword && activeEmail ? (
                <button
                  type="button"
                  onClick={handleQuickLogin}
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 py-2.5 text-sm font-medium text-white shadow-sm transition-all hover:from-blue-700 hover:to-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <KeyRound className="h-4 w-4" />
                  {loading ? "进入中..." : "一键进入"}
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 py-2.5 text-sm font-medium text-white shadow-sm transition-all hover:from-blue-700 hover:to-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loading ? "登录中..." : "登录"}
                </button>
              )}
            </form>
          )}

          {/* 手机号登录表单 */}
          {mode === "login" && tab === "phone" && (
            <form onSubmit={handlePhoneLogin} className="space-y-4">
              <FormField
                label="手机号"
                icon={<Phone className="h-4 w-4" />}
                type="tel"
                value={phone}
                onChange={(v) => {
                  setPhone(v);
                  clearFieldError("phone");
                }}
                placeholder="请输入手机号"
                maxLength={11}
                error={fieldErrors.phone}
              />
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  验证码
                </label>
                <div className="flex gap-3">
                  <div className="relative flex-1">
                    <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                    <input
                      type="text"
                      value={code}
                      onChange={(e) => {
                        setCode(e.target.value);
                        clearFieldError("code");
                      }}
                      placeholder="请输入验证码"
                      maxLength={6}
                      className={clsx(
                        "w-full rounded-lg border py-2.5 pl-10 pr-4 text-sm text-black outline-none transition-colors focus:ring-2 placeholder:text-gray-400 focus:placeholder:text-gray-300",
                        fieldErrors.code
                          ? "border-red-300 focus:border-red-500 focus:ring-red-500/20"
                          : "border-gray-300 focus:border-blue-500 focus:ring-blue-500/20"
                      )}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (!phone || countdown > 0) return;
                      if (!isValidPhone(phone)) {
                        setFieldErrors((prev) => ({
                          ...prev,
                          phone: "请输入正确的手机号",
                        }));
                        return;
                      }
                      clearFieldError("phone");
                      setCountdown(60);
                      // TODO: 调后端发送验证码
                    }}
                    disabled={countdown > 0 || !phone}
                    className="shrink-0 rounded-lg border border-blue-600 px-4 py-2.5 text-sm font-medium text-blue-600 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:border-gray-300 disabled:text-gray-400 disabled:hover:bg-transparent"
                  >
                    {countdown > 0 ? `${countdown}s` : "获取验证码"}
                  </button>
                </div>
                {fieldErrors.code && (
                  <p className="mt-1 text-xs text-red-500">{fieldErrors.code}</p>
                )}
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "登录中..." : "登录"}
              </button>
            </form>
          )}

          {/* 注册表单 */}
          {mode === "register" && (
            <form onSubmit={handleRegister} className="space-y-4">
              <FormField
                label="邮箱"
                icon={<Mail className="h-4 w-4" />}
                type="email"
                value={regEmail}
                onChange={(v) => {
                  setRegEmail(v);
                  clearFieldError("regEmail");
                }}
                placeholder="请输入邮箱"
                error={fieldErrors.regEmail}
              />
              <FormField
                label="密码"
                icon={<Lock className="h-4 w-4" />}
                type={showPassword ? "text" : "password"}
                value={regPassword}
                onChange={(v) => {
                  setRegPassword(v);
                  clearFieldError("regPassword");
                }}
                placeholder="请输入密码（至少 6 位）"
                error={fieldErrors.regPassword}
                rightSlot={
                  <PasswordToggle
                    visible={showPassword}
                    onChange={setShowPassword}
                  />
                }
              />
              <FormField
                label="确认密码"
                icon={<Lock className="h-4 w-4" />}
                type={showConfirmPassword ? "text" : "password"}
                value={regConfirmPassword}
                onChange={(v) => {
                  setRegConfirmPassword(v);
                  clearFieldError("regConfirmPassword");
                }}
                placeholder="请再次输入密码"
                error={fieldErrors.regConfirmPassword}
                rightSlot={
                  <PasswordToggle
                    visible={showConfirmPassword}
                    onChange={setShowConfirmPassword}
                  />
                }
              />
              <FormField
                label="显示名称"
                icon={<User className="h-4 w-4" />}
                value={regName}
                onChange={(v) => {
                  setRegName(v);
                  clearFieldError("regName");
                }}
                placeholder="请输入您的显示名称"
                error={fieldErrors.regName}
              />

              <div className="pt-1">{renderRegisterRememberOptions()}</div>

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "注册中..." : "注册"}
              </button>
            </form>
          )}

          <div className="mt-6 text-center text-sm text-gray-500">
            {mode === "login" ? (
              <>
                还没有账号？{" "}
                <button
                  onClick={() => switchMode("register")}
                  className="font-medium text-blue-600 hover:text-blue-700"
                >
                  注册账号
                </button>
              </>
            ) : (
              <>
                已有账号？{" "}
                <button
                  onClick={() => switchMode("login")}
                  className="font-medium text-blue-600 hover:text-blue-700"
                >
                  返回登录
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
