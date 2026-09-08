COURSE_TYPES = {
    "bxxk": "通识必修",
    "xxxk": "通识选修",
    "kzyxk": "培养方案内",
    "zynknjxk": "非培养方案内",
    "cxxk": "重修",
    "jhnxk": "计划内新生",
}

DEFAULT_BASE_URL = "https://tis.sustech.edu.cn"
DEFAULT_CAS_BASE = "https://cas.sustech.edu.cn"
DEFAULT_CAS_SERVICE = "https://tis.sustech.edu.cn/cas"

MIN_INTERVAL_MS = 1500
DEFAULT_INTERVAL_MS = 1600
DEFAULT_DISCOVERY_INTERVAL_MS = 5000

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) coursecat/1.0 "
    "(personal course-enrollment assistant; serial requests, rate-limit compliant)"
)
