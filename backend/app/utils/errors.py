"""业务错误码表。

规则：业务错误统一 HTTP 200 + code；code 分段管理，前端据此做分支处理。
HTTP 状态码仅保留：401（token 缺失/无效）、403（权限不足，仍可返回 200+code，
按文档约定此处统一 200+code 简化前端处理；网络层 401 由中间件直接返回）。
"""
# 通用
OK = 0
VALIDATION_ERROR = 5001       # 参数校验失败
NOT_FOUND = 5002              # 资源不存在
CONFLICT = 5003               # 状态冲突（如重复提交）
INTERNAL_ERROR = 9000

# 认证（4xxx）
UNAUTHORIZED = 4001           # 未登录 / token 无效
TOKEN_EXPIRED = 4002          # token 过期
PERMISSION_DENIED = 4003      # 无权限
LOGIN_FAILED = 4004           # 用户名或密码错误
ACCOUNT_LOCKED = 4005         # 账号锁定
ACCOUNT_DISABLED = 4006       # 账号停用
MUST_CHANGE_PASSWORD = 4007   # 需先修改初始密码

# 患者端（1xxx）
INVALID_INVITE_CODE = 1001    # 邀请码不存在或格式错误
INVITE_CODE_EXPIRED = 1002    # 邀请码已过期
INVITE_CODE_USED = 1003       # 邀请码已被使用
INVITE_CODE_REVOKED = 1004    # 邀请码已撤回
INVITE_CODE_CANCELLED = 1005  # 邀请码已作废
CONSENT_REQUIRED = 1101       # 未完成知情同意
SESSION_NOT_FOUND = 1102      # 会话不存在
SESSION_EXPIRED = 1103        # 断点续答已过期
INVALID_ANSWERS = 1104        # 作答数据非法（漏题/超范围）
PHQ4_ALREADY_SUBMITTED = 1105 # 快筛已提交
RESUME_CONFLICT = 1106        # 续答状态冲突

# 撤回（12xx）
REVOKE_TOO_LATE = 1201        # 超过 24 小时撤回期限
ALREADY_REVOKED = 1202        # 该数据已被撤回
NOT_REVOKABLE = 1203          # 当前状态不可撤回
REVOKE_TOKEN_MISMATCH = 1204  # 撤回确认文字不符
