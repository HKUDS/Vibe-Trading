export type DesktopLocale = "en" | "zh-CN" | "ja" | "ko" | "ar";

export type DesktopMessages = {
  startupFailureTitle: string;
  backendAlreadyRunning: string;
  backendUnexpectedExit: string;
  backendStarting: string;
  backendReady: string;
  backendNotStarted: string;
  backendExitedEarly: string;
  backendHealthTimeout: string;
  backendNotFound: string;
  portUnavailable: string;
  credentialEncryptionUnavailable: string;
  credentialFileUnsupported: string;
  credentialKeyUnsupported: string;
  credentialRequestInvalid: string;
  credentialStoreUnavailable: string;
  closingService: string;
  menuApplication: string;
  menuRestartService: string;
  menuOpenLogs: string;
  menuQuit: string;
  menuView: string;
  menuReload: string;
  menuDeveloperTools: string;
  menuActualSize: string;
  menuZoomIn: string;
  menuZoomOut: string;
  menuFullscreen: string;
  loadingTitle: string;
  loadingMessage: string;
  loadingRetry: string;
  loadingOpenLogs: string;
  loadingFailedTitle: string;
  loadingRestartingTitle: string;
};

export type DesktopRendererLocale = {
  locale: DesktopLocale;
  direction: "ltr" | "rtl";
  messages: Pick<
    DesktopMessages,
    | "loadingTitle"
    | "loadingMessage"
    | "loadingRetry"
    | "loadingOpenLogs"
    | "loadingFailedTitle"
    | "loadingRestartingTitle"
  >;
};

export const supportedDesktopLocales: readonly DesktopLocale[] = [
  "en",
  "zh-CN",
  "ja",
  "ko",
  "ar",
];

const messages: Record<DesktopLocale, DesktopMessages> = {
  en: {
    startupFailureTitle: "Vibe-Trading Desktop failed to start",
    backendAlreadyRunning: "The backend process is already running.",
    backendUnexpectedExit: "The Vibe-Trading backend exited unexpectedly (code {code}).",
    backendStarting: "Backend started; waiting for health check · {port}",
    backendReady: "Local service is ready · {port}",
    backendNotStarted: "The backend has not started.",
    backendExitedEarly: "The Vibe-Trading backend exited before it was ready (code {code}).\n{details}",
    backendHealthTimeout: "Timed out waiting for the Vibe-Trading backend.\n{details}",
    backendNotFound: "Could not find vibe-trading.exe. Install the backend first or set VIBE_TRADING_EXECUTABLE.",
    portUnavailable: "Could not allocate a local port.",
    credentialEncryptionUnavailable: "Credential encryption is unavailable for this Windows user session.",
    credentialFileUnsupported: "The desktop credential file format is not supported.",
    credentialKeyUnsupported: "This credential key is not supported.",
    credentialRequestInvalid: "The credential request is invalid.",
    credentialStoreUnavailable: "Secure credential storage has not been initialized.",
    closingService: "Closing the local service…",
    menuApplication: "Application",
    menuRestartService: "Restart local service",
    menuOpenLogs: "Open log folder",
    menuQuit: "Quit",
    menuView: "View",
    menuReload: "Reload",
    menuDeveloperTools: "Developer tools",
    menuActualSize: "Actual size",
    menuZoomIn: "Zoom in",
    menuZoomOut: "Zoom out",
    menuFullscreen: "Fullscreen",
    loadingTitle: "Starting Vibe-Trading Desktop",
    loadingMessage: "The desktop app is preparing the local service. The first start may take a moment.",
    loadingRetry: "Retry",
    loadingOpenLogs: "Open log folder",
    loadingFailedTitle: "Startup failed",
    loadingRestartingTitle: "Restarting",
  },
  "zh-CN": {
    startupFailureTitle: "Vibe-Trading Desktop 启动失败",
    backendAlreadyRunning: "后端进程已经在运行。",
    backendUnexpectedExit: "Vibe-Trading 后端意外退出（代码 {code}）。",
    backendStarting: "后端已启动，正在等待健康检查 · {port}",
    backendReady: "本地服务已就绪 · {port}",
    backendNotStarted: "后端尚未启动。",
    backendExitedEarly: "Vibe-Trading 后端在就绪前退出（代码 {code}）。\n{details}",
    backendHealthTimeout: "等待 Vibe-Trading 后端就绪超时。\n{details}",
    backendNotFound: "找不到 vibe-trading.exe。请先安装后端，或设置 VIBE_TRADING_EXECUTABLE。",
    portUnavailable: "无法分配本地端口。",
    credentialEncryptionUnavailable: "当前 Windows 用户会话无法使用凭据加密。",
    credentialFileUnsupported: "桌面凭据文件格式不受支持。",
    credentialKeyUnsupported: "不支持该凭据键。",
    credentialRequestInvalid: "凭据请求无效。",
    credentialStoreUnavailable: "安全凭据存储尚未初始化。",
    closingService: "正在关闭本地服务…",
    menuApplication: "应用",
    menuRestartService: "重启本地服务",
    menuOpenLogs: "打开日志文件夹",
    menuQuit: "退出",
    menuView: "视图",
    menuReload: "刷新",
    menuDeveloperTools: "开发者工具",
    menuActualSize: "实际大小",
    menuZoomIn: "放大",
    menuZoomOut: "缩小",
    menuFullscreen: "全屏",
    loadingTitle: "正在启动 Vibe-Trading Desktop",
    loadingMessage: "桌面端正在准备本地服务，第一次启动可能需要一点时间。",
    loadingRetry: "重试",
    loadingOpenLogs: "打开日志文件夹",
    loadingFailedTitle: "启动失败",
    loadingRestartingTitle: "正在重新启动",
  },
  ja: {
    startupFailureTitle: "Vibe-Trading Desktop の起動に失敗しました",
    backendAlreadyRunning: "バックエンドプロセスはすでに実行中です。",
    backendUnexpectedExit: "Vibe-Trading バックエンドが予期せず終了しました（コード {code}）。",
    backendStarting: "バックエンドを起動しました。ヘルスチェックを待っています · {port}",
    backendReady: "ローカルサービスの準備ができました · {port}",
    backendNotStarted: "バックエンドはまだ起動していません。",
    backendExitedEarly: "Vibe-Trading バックエンドが準備完了前に終了しました（コード {code}）。\n{details}",
    backendHealthTimeout: "Vibe-Trading バックエンドの準備待ちがタイムアウトしました。\n{details}",
    backendNotFound: "vibe-trading.exe が見つかりません。バックエンドをインストールするか、VIBE_TRADING_EXECUTABLE を設定してください。",
    portUnavailable: "ローカルポートを割り当てられませんでした。",
    credentialEncryptionUnavailable: "この Windows ユーザーセッションでは資格情報の暗号化を利用できません。",
    credentialFileUnsupported: "デスクトップ資格情報ファイルの形式はサポートされていません。",
    credentialKeyUnsupported: "この資格情報キーはサポートされていません。",
    credentialRequestInvalid: "資格情報の要求が無効です。",
    credentialStoreUnavailable: "安全な資格情報ストアが初期化されていません。",
    closingService: "ローカルサービスを終了しています…",
    menuApplication: "アプリケーション",
    menuRestartService: "ローカルサービスを再起動",
    menuOpenLogs: "ログフォルダーを開く",
    menuQuit: "終了",
    menuView: "表示",
    menuReload: "再読み込み",
    menuDeveloperTools: "開発者ツール",
    menuActualSize: "実際のサイズ",
    menuZoomIn: "拡大",
    menuZoomOut: "縮小",
    menuFullscreen: "全画面表示",
    loadingTitle: "Vibe-Trading Desktop を起動しています",
    loadingMessage: "ローカルサービスを準備しています。初回起動には少し時間がかかる場合があります。",
    loadingRetry: "再試行",
    loadingOpenLogs: "ログフォルダーを開く",
    loadingFailedTitle: "起動に失敗しました",
    loadingRestartingTitle: "再起動しています",
  },
  ko: {
    startupFailureTitle: "Vibe-Trading Desktop를 시작하지 못했습니다",
    backendAlreadyRunning: "백엔드 프로세스가 이미 실행 중입니다.",
    backendUnexpectedExit: "Vibe-Trading 백엔드가 예기치 않게 종료되었습니다(코드 {code}).",
    backendStarting: "백엔드가 시작되었습니다. 상태 확인을 기다리는 중 · {port}",
    backendReady: "로컬 서비스가 준비되었습니다 · {port}",
    backendNotStarted: "백엔드가 아직 시작되지 않았습니다.",
    backendExitedEarly: "Vibe-Trading 백엔드가 준비되기 전에 종료되었습니다(코드 {code}).\n{details}",
    backendHealthTimeout: "Vibe-Trading 백엔드 준비를 기다리는 동안 시간이 초과되었습니다.\n{details}",
    backendNotFound: "vibe-trading.exe를 찾을 수 없습니다. 백엔드를 설치하거나 VIBE_TRADING_EXECUTABLE을 설정하세요.",
    portUnavailable: "로컬 포트를 할당할 수 없습니다.",
    credentialEncryptionUnavailable: "현재 Windows 사용자 세션에서 자격 증명 암호화를 사용할 수 없습니다.",
    credentialFileUnsupported: "데스크톱 자격 증명 파일 형식이 지원되지 않습니다.",
    credentialKeyUnsupported: "지원되지 않는 자격 증명 키입니다.",
    credentialRequestInvalid: "자격 증명 요청이 올바르지 않습니다.",
    credentialStoreUnavailable: "보안 자격 증명 저장소가 초기화되지 않았습니다.",
    closingService: "로컬 서비스를 종료하는 중…",
    menuApplication: "애플리케이션",
    menuRestartService: "로컬 서비스 다시 시작",
    menuOpenLogs: "로그 폴더 열기",
    menuQuit: "종료",
    menuView: "보기",
    menuReload: "새로 고침",
    menuDeveloperTools: "개발자 도구",
    menuActualSize: "실제 크기",
    menuZoomIn: "확대",
    menuZoomOut: "축소",
    menuFullscreen: "전체 화면",
    loadingTitle: "Vibe-Trading Desktop 시작 중",
    loadingMessage: "로컬 서비스를 준비하고 있습니다. 처음 시작할 때는 잠시 시간이 걸릴 수 있습니다.",
    loadingRetry: "다시 시도",
    loadingOpenLogs: "로그 폴더 열기",
    loadingFailedTitle: "시작 실패",
    loadingRestartingTitle: "다시 시작하는 중",
  },
  ar: {
    startupFailureTitle: "تعذّر بدء Vibe-Trading Desktop",
    backendAlreadyRunning: "عملية الواجهة الخلفية قيد التشغيل بالفعل.",
    backendUnexpectedExit: "توقفت الواجهة الخلفية لـ Vibe-Trading بشكل غير متوقع (الرمز {code}).",
    backendStarting: "بدأت الواجهة الخلفية؛ جارٍ انتظار فحص السلامة · {port}",
    backendReady: "الخدمة المحلية جاهزة · {port}",
    backendNotStarted: "لم تبدأ الواجهة الخلفية بعد.",
    backendExitedEarly: "توقفت الواجهة الخلفية لـ Vibe-Trading قبل أن تصبح جاهزة (الرمز {code}).\n{details}",
    backendHealthTimeout: "انتهت مهلة انتظار جاهزية الواجهة الخلفية لـ Vibe-Trading.\n{details}",
    backendNotFound: "تعذّر العثور على vibe-trading.exe. ثبّت الواجهة الخلفية أولاً أو اضبط VIBE_TRADING_EXECUTABLE.",
    portUnavailable: "تعذّر تخصيص منفذ محلي.",
    credentialEncryptionUnavailable: "تشفير بيانات الاعتماد غير متاح لجلسة مستخدم Windows الحالية.",
    credentialFileUnsupported: "تنسيق ملف بيانات اعتماد سطح المكتب غير مدعوم.",
    credentialKeyUnsupported: "مفتاح بيانات الاعتماد هذا غير مدعوم.",
    credentialRequestInvalid: "طلب بيانات الاعتماد غير صالح.",
    credentialStoreUnavailable: "لم تتم تهيئة مخزن بيانات الاعتماد الآمن.",
    closingService: "جارٍ إغلاق الخدمة المحلية…",
    menuApplication: "التطبيق",
    menuRestartService: "إعادة تشغيل الخدمة المحلية",
    menuOpenLogs: "فتح مجلد السجلات",
    menuQuit: "إنهاء",
    menuView: "عرض",
    menuReload: "إعادة تحميل",
    menuDeveloperTools: "أدوات المطور",
    menuActualSize: "الحجم الفعلي",
    menuZoomIn: "تكبير",
    menuZoomOut: "تصغير",
    menuFullscreen: "ملء الشاشة",
    loadingTitle: "جارٍ بدء Vibe-Trading Desktop",
    loadingMessage: "يُجهّز تطبيق سطح المكتب الخدمة المحلية. قد يستغرق التشغيل الأول بعض الوقت.",
    loadingRetry: "إعادة المحاولة",
    loadingOpenLogs: "فتح مجلد السجلات",
    loadingFailedTitle: "فشل بدء التشغيل",
    loadingRestartingTitle: "جارٍ إعادة التشغيل",
  },
};

export function resolveDesktopLocale(rawLocale: string | undefined): DesktopLocale {
  const normalized = (rawLocale ?? "").trim().toLowerCase().replaceAll("_", "-");
  if (normalized === "zh" || normalized.startsWith("zh-cn") || normalized.startsWith("zh-hans")) {
    return "zh-CN";
  }
  if (normalized === "ja" || normalized.startsWith("ja-")) return "ja";
  if (normalized === "ko" || normalized.startsWith("ko-")) return "ko";
  if (normalized === "ar" || normalized.startsWith("ar-")) return "ar";
  return "en";
}

export function getDesktopMessages(locale: DesktopLocale): DesktopMessages {
  return messages[locale];
}

export function getRendererLocale(locale: DesktopLocale): DesktopRendererLocale {
  const localeMessages = getDesktopMessages(locale);
  return {
    locale,
    direction: locale === "ar" ? "rtl" : "ltr",
    messages: {
      loadingTitle: localeMessages.loadingTitle,
      loadingMessage: localeMessages.loadingMessage,
      loadingRetry: localeMessages.loadingRetry,
      loadingOpenLogs: localeMessages.loadingOpenLogs,
      loadingFailedTitle: localeMessages.loadingFailedTitle,
      loadingRestartingTitle: localeMessages.loadingRestartingTitle,
    },
  };
}

export function formatDesktopMessage(
  template: string,
  values: Record<string, string | number | null | undefined>,
): string {
  return template.replace(/\{([a-zA-Z0-9_]+)\}/gu, (_match, key: string) => {
    const value = values[key];
    return value === null || value === undefined ? "" : String(value);
  });
}
