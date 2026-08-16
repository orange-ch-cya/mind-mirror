"""禁用词表与安全表述映射（文档 10.1 第四层 / 10.2）。

核心替换逻辑硬编码在代码中，即使配置表为空也会执行基础替换——
这是"不标签化"底线在结果生成链路上的强制实现，不依赖人工遵守。
若检测到命中，同时返回替换结果与警告标记，供管理员排查配置不当的规则。
"""
import logging

logger = logging.getLogger(__name__)

# 禁用表述 → 安全替换表述（文档 10.2 默认表）
DEFAULT_DISALLOWED_MAP = {
    "你有抑郁倾向": "您近期的情绪状态呈现出一些需要关注的特征",
    "你可能是焦虑症": "您近期的焦虑水平处于偏高的范围",
    "你的心理问题较严重": "您近期在多维度上的自评分数相对偏高",
    "你正常": "您近期的状态整体平稳",
    "你没病": "您近期的状态整体平稳",
    "诊断为": "评估结果显示",
    "确诊为": "评估结果显示",
    "患有": "呈现出",
    "罹患": "呈现出",
    "症状": "表现",
    "异常": "偏离常见范围",
    "不正常": "处于偏高的区间",
    "治疗": "专业支持",
    "治病": "专业支持",
    "病人": "个体",
    "患者": "个体",
    "抑郁倾向": "情绪状态需要关注的特征",
    "焦虑症": "焦虑水平偏高的范围",
    "重度抑郁症": "显著偏高的情绪状态水平",
}

# 额外的短词拦截（防止以词根形式出现在任何自动生成文本中）
EXTRA_BLOCKED_WORDS = ["确诊", "诊断", "患病", "吃药", "用药", "住院"]


def sanitize_output(text):
    """对自动生成的结果文本执行禁用词过滤。

    返回 (safe_text, warned)：
    - safe_text: 替换后的安全文本；
    - warned: 布尔，是否命中过禁用表述（用于记录警告日志）。
    """
    if not text:
        return text, False

    warned = False
    safe = text
    for bad, good in DEFAULT_DISALLOWED_MAP.items():
        if bad in safe:
            safe = safe.replace(bad, good)
            warned = True

    # 命中"硬拦截"短词但不在映射表中时，同样记警告
    for word in EXTRA_BLOCKED_WORDS:
        if word in safe:
            warned = True
            logger.warning("sanitize: 文本命中禁用词根 '%s'，请检查规则配置", word)

    if warned:
        logger.warning("sanitize: 输出文本经过禁用词替换，原文本=%r", text[:200])
    return safe, warned


def contains_disallowed(text):
    """检查文本是否包含禁用表述（用于后台录入软校验提醒）。"""
    hits = []
    for bad in DEFAULT_DISALLOWED_MAP:
        if bad in text:
            hits.append(bad)
    for word in EXTRA_BLOCKED_WORDS:
        if word in text:
            hits.append(word)
    return hits
