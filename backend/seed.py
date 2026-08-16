"""种子数据脚本（幂等，可重复执行）。

用法：
    python seed.py                 # 开发环境
    python seed.py --env production

内容（文档 8.1 / 8.2 / 5.4 / 6.1）：
- 超级管理员账号（初始密码首次登录强制修改）
- 系统配置默认值
- 首批量表：PHQ-4/GAD-7/PHQ-9/HADS/SDS/SAS/PSS/ESS/PSQI/SCL-90/IES-R
- 组合包：焦虑/抑郁/情绪综合/睡眠/压力/全面筛查
- 推送规则（文档 3.4 七个分支）
- 分科规则（预置基础规则，管理员可修改扩充）
- 常模数据（近似值，正式上线前需专业审定）
"""
import json
import sys

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import (Norm, PushRule, ReferralRule, Scale, ScaleItem,
                        ScalePackage, SystemConfig, User)

from seed_data.scales_core import (ESS_ITEMS, GAD7_ITEMS, HADS_ITEMS,
                                   PHQ4_ITEMS, PHQ9_ITEMS, PSQI_ITEMS,
                                   PSS_ITEMS, SAS_ITEMS, SDS_ITEMS)
from seed_data.scales_iesr import IESR_ITEMS
from seed_data.scales_scl90 import SCL90_ITEMS

ADMIN_USERNAME = "admin"
ADMIN_INITIAL_PASSWORD = "Admin@1234"  # 首次登录强制修改

SCALES = [
    {
        "abbreviation": "PHQ-4", "name_zh": "患者健康问卷4题版",
        "name_en": "Patient Health Questionnaire-4",
        "source": "Kroenke K, et al. An ultra-brief screening scale for anxiety and depression: the PHQ-4. Psychosomatics. 2009.",
        "description": "PHQ-4 是经过广泛验证的超简短心理状态筛查工具，包含 4 道题，前 2 题测量焦虑维度、后 2 题测量抑郁维度。总分范围 0-12 分，作为平台入口的快速筛查工具。",
        "target_population": "成人", "estimated_minutes": 1,
        "items": PHQ4_ITEMS,
    },
    {
        "abbreviation": "GAD-7", "name_zh": "广泛性焦虑障碍量表",
        "name_en": "Generalized Anxiety Disorder-7",
        "source": "Spitzer RL, et al. A brief measure for assessing generalized anxiety disorder: the GAD-7. Arch Intern Med. 2006.",
        "description": "GAD-7 用于评估近两周广泛性焦虑症状的频率，共 7 题，总分 0-21 分。常模参考：0-4 分正常范围，5-9 分轻度，10-14 分中度，15-21 分重度。",
        "target_population": "成人", "estimated_minutes": 2,
        "items": GAD7_ITEMS,
    },
    {
        "abbreviation": "PHQ-9", "name_zh": "患者健康问卷抑郁量表",
        "name_en": "Patient Health Questionnaire-9",
        "source": "Kroenke K, et al. The PHQ-9: validity of a brief depression severity measure. J Gen Intern Med. 2001.",
        "description": "PHQ-9 依据 DSM 抑郁诊断标准编制，评估近两周抑郁症状频率，共 9 题，总分 0-27 分。常模参考：0-4 分正常范围，5-9 分轻度，10-14 分中度，15-19 分中重度，20-27 分重度。",
        "target_population": "成人", "estimated_minutes": 2,
        "items": PHQ9_ITEMS,
    },
    {
        "abbreviation": "HADS", "name_zh": "医院焦虑抑郁量表",
        "name_en": "Hospital Anxiety and Depression Scale",
        "source": "Zigmond AS, Snaith RP. The Hospital Anxiety and Depression Scale. Acta Psychiatr Scand. 1983.",
        "description": "HADS 共 14 题，包含焦虑（HADS-A，奇数题）与抑郁（HADS-D，偶数题）两个分量表，各 7 题，每个分量表 0-21 分。常在医疗场景中用于筛查。分量表得分 8-10 分提示可疑，11 分及以上提示可能存在相关问题。",
        "target_population": "成人", "estimated_minutes": 3,
        "items": HADS_ITEMS,
    },
    {
        "abbreviation": "SDS", "name_zh": "抑郁自评量表",
        "name_en": "Self-Rating Depression Scale",
        "source": "Zung WWK. A self-rating depression scale. Arch Gen Psychiatry. 1965.",
        "description": "SDS 是经典的抑郁自评工具，共 20 题，每题 1-4 级计分，总分 20-80 分。标准分（总分×1.25）≥53 分提示可能存在抑郁状态。",
        "target_population": "成人", "estimated_minutes": 5,
        "items": SDS_ITEMS,
    },
    {
        "abbreviation": "SAS", "name_zh": "焦虑自评量表",
        "name_en": "Self-Rating Anxiety Scale",
        "source": "Zung WWK. A rating instrument for anxiety disorders. Psychosomatics. 1971.",
        "description": "SAS 是经典的焦虑自评工具，共 20 题，每题 1-4 级计分，总分 20-80 分。标准分（总分×1.25）≥50 分提示可能存在焦虑状态。",
        "target_population": "成人", "estimated_minutes": 5,
        "items": SAS_ITEMS,
    },
    {
        "abbreviation": "PSS", "name_zh": "压力知觉量表",
        "name_en": "Perceived Stress Scale",
        "source": "Cohen S, Kamarck T, Mermelstein R. A global measure of perceived stress. J Health Soc Behav. 1983.",
        "description": "PSS 用于评估近一个月感知到的压力水平，本版本为 10 题版，每题 0-4 级计分，总分 0-40 分，分数越高表示感知压力越大。",
        "target_population": "成人", "estimated_minutes": 3,
        "items": PSS_ITEMS,
    },
    {
        "abbreviation": "ESS", "name_zh": "爱泼沃斯嗜睡量表",
        "name_en": "Epworth Sleepiness Scale",
        "source": "Johns MW. A new method for measuring daytime sleepiness: the Epworth sleepiness scale. Sleep. 1991.",
        "description": "ESS 用于评估日常生活中的嗜睡倾向，共 8 题，每题 0-3 级计分，总分 0-24 分。总分 >10 分提示存在过度日间嗜睡。",
        "target_population": "成人", "estimated_minutes": 2,
        "items": ESS_ITEMS,
    },
    {
        "abbreviation": "PSQI", "name_zh": "匹兹堡睡眠质量指数",
        "name_en": "Pittsburgh Sleep Quality Index",
        "source": "Buysse DJ, et al. The Pittsburgh Sleep Quality Index: a new instrument for psychiatric practice and research. Psychiatry Res. 1989.",
        "description": "PSQI 用于评估近一个月的睡眠质量，本版本收录 19 题自评部分，覆盖入睡、睡眠时长、睡眠效率、睡眠障碍、催眠药物、日间功能等方面。原版按 7 个成分加权计分，本平台 MVP 阶段以求和范式近似，成分计分将在后续迭代完善。",
        "target_population": "成人", "estimated_minutes": 5,
        "items": PSQI_ITEMS,
    },
    {
        "abbreviation": "SCL-90", "name_zh": "症状自评量表",
        "name_en": "Symptom Checklist-90",
        "source": "Derogatis LR. SCL-90-R: Administration, Scoring and Procedures Manual. 1994.",
        "description": "SCL-90 共 90 题，覆盖躯体化、强迫症状、人际关系敏感、抑郁、焦虑、敌对、恐怖、偏执、精神病性及其他共 10 个因子维度，每题 1-5 级计分，用于全面筛查可能的心理困扰维度。",
        "target_population": "成人", "estimated_minutes": 15,
        "items": SCL90_ITEMS,
    },
    {
        "abbreviation": "IES-R", "name_zh": "事件影响量表修订版",
        "name_en": "Impact of Event Scale-Revised",
        "source": "Weiss DS, Marmar CR. The Impact of Event Scale-Revised. 1997.",
        "description": "IES-R 用于评估特定应激事件（如创伤经历）后的心理反应，共 22 题，覆盖侵入、回避、高唤醒三个维度，每题 0-4 级计分，总分 0-88 分。",
        "target_population": "成人", "estimated_minutes": 5,
        "items": IESR_ITEMS,
    },
]

PACKAGES = [
    {"name": "焦虑深度包", "description": "针对焦虑相关困扰的交叉验证组合：GAD-7 关注近两周焦虑症状频率，SAS 评估更广泛的焦虑体验，HADS 提供医院筛查视角。",
     "estimated_time_minutes": 10, "scales": ["GAD-7", "SAS", "HADS"]},
    {"name": "抑郁深度包", "description": "针对抑郁相关困扰的交叉验证组合：PHQ-9 与快筛同源但更详细，SDS 为经典抑郁自评工具，HADS 提供医院筛查视角。",
     "estimated_time_minutes": 10, "scales": ["PHQ-9", "SDS", "HADS"]},
    {"name": "情绪综合包", "description": "当焦虑与抑郁症状同时明显时使用的全面评估组合：GAD-7 与 PHQ-9 评估两大情绪维度，HADS 双分量表交叉验证，SCL-90 提供多维度视角。",
     "estimated_time_minutes": 25, "scales": ["GAD-7", "PHQ-9", "HADS", "SCL-90"]},
    {"name": "睡眠专项包", "description": "针对睡眠困扰的专项评估：PSQI 评估近一个月整体睡眠质量，ESS 评估日间嗜睡倾向。",
     "estimated_time_minutes": 7, "scales": ["PSQI", "ESS"]},
    {"name": "压力应激包", "description": "针对近期压力事件的专项评估：PSS 评估感知压力水平，IES-R 评估应激事件后的心理反应。",
     "estimated_time_minutes": 8, "scales": ["PSS", "IES-R"]},
    {"name": "全面筛查包", "description": "当困扰无明显偏向时的广泛筛查：SCL-90 覆盖 10 个症状维度，帮助发现可能未被意识到的困扰维度。",
     "estimated_time_minutes": 15, "scales": ["SCL-90"]},
]

PUSH_RULES = [
    {
        "name": "焦虑分支：焦虑维度≥4且抑郁维度<3",
        "priority": 10, "package": "焦虑深度包",
        "conditions": [
            {"source": "phq4", "dimension": "anxiety", "op": "gte", "value": 4},
            {"source": "phq4", "dimension": "depression", "op": "lt", "value": 3},
        ],
    },
    {
        "name": "抑郁分支：抑郁维度≥4且焦虑维度<3",
        "priority": 10, "package": "抑郁深度包",
        "conditions": [
            {"source": "phq4", "dimension": "depression", "op": "gte", "value": 4},
            {"source": "phq4", "dimension": "anxiety", "op": "lt", "value": 3},
        ],
    },
    {
        "name": "混合分支：焦虑与抑郁均偏高",
        "priority": 10, "package": "情绪综合包",
        "conditions": [
            {"source": "phq4", "dimension": "anxiety", "op": "gte", "value": 4},
            {"source": "phq4", "dimension": "depression", "op": "gte", "value": 4},
        ],
    },
    {
        "name": "睡眠分支：总分<6且睡眠问题突出",
        "priority": 20, "package": "睡眠专项包",
        "conditions": [
            {"source": "phq4", "dimension": "total", "op": "lt", "value": 6},
            {"source": "supplement", "dimension": "sleep", "op": "eq", "value": 1},
        ],
    },
    {
        "name": "压力分支：总分<6且近期重大压力事件",
        "priority": 20, "package": "压力应激包",
        "conditions": [
            {"source": "phq4", "dimension": "total", "op": "lt", "value": 6},
            {"source": "supplement", "dimension": "stress", "op": "eq", "value": 1},
        ],
    },
    {
        "name": "全面筛查分支：总分≥6（非特异性困扰）",
        "priority": 30, "package": "全面筛查包",
        "conditions": [
            {"source": "phq4", "dimension": "total", "op": "gte", "value": 6},
        ],
    },
]

# 分科规则：condition 里 scale 用缩写占位，seed 时替换为真实 ID。
REFERRAL_RULES = [
    {
        "name": "GAD-7 显著偏高", "priority": 10, "style": "alert",
        "scale": "GAD-7", "dimension": "total", "op": "gte", "value": 15,
        "tags": "建议精神科就诊",
        "doctor": "GAD-7 总分显著偏高，建议精神科进一步评估。",
        "parent": "孩子在焦虑相关的自评中得分处于显著偏高的范围。这不意味着孩子一定存在焦虑问题，但提示孩子的情绪状态需要专业关注。建议您近期带孩子前往医院的临床心理科或精神科进行全面评估，并可将这份报告作为参考与医生交流。",
    },
    {
        "name": "GAD-7 中度偏高", "priority": 20, "style": "warning",
        "scale": "GAD-7", "dimension": "total", "op": "between", "value": [10, 14],
        "tags": "建议进一步评估",
        "doctor": "GAD-7 总分处于中度偏高范围，建议进一步评估。",
        "parent": "孩子在焦虑相关的自评中得分处于中等偏高的范围。这提示孩子的情绪状态值得关注，建议您与学校心理老师或专业医生沟通，评估是否需要进一步的专业支持。",
    },
    {
        "name": "PHQ-9 显著偏高", "priority": 10, "style": "alert",
        "scale": "PHQ-9", "dimension": "total", "op": "gte", "value": 15,
        "tags": "建议精神科就诊",
        "doctor": "PHQ-9 总分显著偏高，建议精神科进一步评估。",
        "parent": "孩子在情绪相关的自评中得分处于显著偏高的范围。这不意味着孩子一定存在情绪问题，但提示孩子的情绪状态需要专业关注。建议您近期安排孩子与心理科或精神科医生进行一次沟通，由专业人士进行全面评估。",
    },
    {
        "name": "PHQ-9 中度偏高", "priority": 20, "style": "warning",
        "scale": "PHQ-9", "dimension": "total", "op": "between", "value": [10, 14],
        "tags": "建议进一步评估",
        "doctor": "PHQ-9 总分处于中度偏高范围，建议进一步评估。",
        "parent": "孩子在情绪相关的自评中得分处于中等偏高的范围。这提示孩子的情绪状态值得关注，建议您与专业人士沟通，评估是否需要进一步的支持。",
    },
    {
        "name": "HADS 焦虑分量表偏高", "priority": 20, "style": "warning",
        "scale": "HADS", "dimension": "焦虑", "op": "gte", "value": 11,
        "tags": "建议进一步评估",
        "doctor": "HADS 焦虑分量表得分≥11，提示焦虑相关问题可能，建议进一步评估。",
        "parent": "孩子在焦虑分量表上的得分较高。这提示孩子可能存在一些焦虑相关的困扰，值得与专业人士沟通，评估是否需要进一步支持。",
    },
    {
        "name": "HADS 抑郁分量表偏高", "priority": 20, "style": "warning",
        "scale": "HADS", "dimension": "抑郁", "op": "gte", "value": 11,
        "tags": "建议进一步评估",
        "doctor": "HADS 抑郁分量表得分≥11，提示抑郁相关问题可能，建议进一步评估。",
        "parent": "孩子在抑郁分量表上的得分较高。这提示孩子可能存在一些情绪低落的困扰，值得与专业人士沟通，评估是否需要进一步支持。",
    },
    {
        "name": "SDS 总分偏高", "priority": 20, "style": "warning",
        "scale": "SDS", "dimension": "total", "op": "gte", "value": 43,
        "tags": "建议进一步评估",
        "doctor": "SDS 原始分≥43（标准分≥53），提示抑郁状态可能，建议进一步评估。",
        "parent": "孩子在抑郁自评中的得分处于偏高的范围。这不一定意味着孩子有抑郁症，但提示孩子的情绪状态需要更多关注，建议与专业人士沟通评估。",
    },
    {
        "name": "SAS 总分偏高", "priority": 20, "style": "warning",
        "scale": "SAS", "dimension": "total", "op": "gte", "value": 40,
        "tags": "建议进一步评估",
        "doctor": "SAS 原始分≥40（标准分≥50），提示焦虑状态可能，建议进一步评估。",
        "parent": "孩子在焦虑自评中的得分处于偏高的范围。这提示孩子的情绪状态值得关注，建议与专业人士沟通评估。",
    },
    {
        "name": "PSQI 睡眠质量提示", "priority": 20, "style": "warning",
        "scale": "PSQI", "dimension": "total", "op": "gte", "value": 6,
        "tags": "建议睡眠关注",
        "doctor": "PSQI 总分偏高，提示睡眠质量不佳，建议关注睡眠状况并排查诱因。",
        "parent": "孩子的睡眠自评结果提示睡眠质量需要关注。睡眠问题可能与情绪、学习压力等相互影响，建议留意孩子的作息习惯，必要时与医生沟通。",
    },
    {
        "name": "SCL-90 抑郁因子偏高", "priority": 30, "style": "warning",
        "scale": "SCL-90", "dimension": "抑郁", "op": "gte", "value": 35,
        "tags": "建议进一步评估",
        "doctor": "SCL-90 抑郁因子分偏高，建议结合其他量表综合评估。",
        "parent": "孩子在全面自评中的情绪相关维度得分偏高，建议与专业人士沟通，综合了解孩子的整体状态。",
    },
]

# 常模（近似值，正式上线前需以专业来源审定替换）
NORMS = [
    {"scale": "GAD-7", "mean": 5.2, "std_dev": 4.4,
     "thresholds": {"mild": 5, "moderate": 10, "severe": 15}},
    {"scale": "PHQ-9", "mean": 6.0, "std_dev": 5.5,
     "thresholds": {"mild": 5, "moderate": 10, "severe": 15}},
    {"scale": "HADS", "mean": 7.5, "std_dev": 4.5,
     "thresholds": {"suspicious": 8, "probable": 11}},
    {"scale": "SDS", "mean": 33.5, "std_dev": 10.5,
     "thresholds": {"mild": 43, "moderate": 50, "severe": 58}},
    {"scale": "SAS", "mean": 30.0, "std_dev": 9.0,
     "thresholds": {"mild": 40, "moderate": 50, "severe": 60}},
    {"scale": "PSQI", "mean": 5.0, "std_dev": 3.0,
     "thresholds": {"poor": 6}},
    {"scale": "PSS", "mean": 13.0, "std_dev": 5.5, "thresholds": {}},
    {"scale": "ESS", "mean": 6.0, "std_dev": 4.0,
     "thresholds": {"excessive": 10}},
    {"scale": "SCL-90", "mean": 130.0, "std_dev": 35.0,
     "thresholds": {"moderate": 160}},
]

DEFAULT_CONFIGS = [
    ("revoke_hours", 24, "int", "患者撤回时限（小时），默认 24"),
    ("session_resume_hours", 24, "int", "断点续答有效期（小时）"),
    ("assessment_timeout_minutes", 30, "int", "作答超时提醒时间（分钟）"),
    ("login_max_failures", 5, "int", "连续登录失败锁定阈值"),
    ("login_lock_minutes", 30, "int", "登录锁定分钟数"),
    ("patient_closing_message",
     "感谢您的认真参与。自我觉察是关爱自己的第一步。您愿意花时间了解自己的状态，这件事本身就值得肯定。",
     "str", "患者结果页结束语"),
    ("patient_encouragements",
     ["心理健康和身体健康一样重要，您今天的关注是对自己的善待。",
      "每个人的情绪都会有起伏，这完全正常，您不是一个人在面对。",
      "请记得，寻求帮助不是软弱，而是一种力量和智慧的体现。"],
     "json", "患者结果页鼓励话语库（随机展示）"),
    ("patient_tips",
     ["规律作息：尽量保持固定的睡眠和起床时间，身体的节律对情绪有直接影响。",
      "适度运动：每天 20-30 分钟的快走或伸展，动起来就是好的开始。",
      "正念呼吸：感到紧张时，试试 4-7-8 呼吸法——吸气 4 秒，屏住 7 秒，缓慢呼气 8 秒。",
      "社交联结：和信任的人聊聊天，人际联结是情绪缓冲的重要资源。",
      "减少信息过载：适当减少刷手机的时间，特别是睡前，给大脑留一些安静的空间。"],
     "json", "患者结果页调节小贴士库"),
    ("patient_contact_hint",
     "您的完整测评数据已安全地发送给向您提供邀请码的人士。如需了解详细结果和专业解读，请直接联系邀请您参与测评的人士。出于对您的保护，平台不会直接向您展示分数和详细报告。",
     "str", "患者结果页联系邀请人提示"),
]


def seed_admin():
    if User.query.filter_by(username=ADMIN_USERNAME).first():
        return
    user = User(username=ADMIN_USERNAME,
                password_hash=generate_password_hash(ADMIN_INITIAL_PASSWORD),
                display_name="超级管理员", role="admin",
                must_change_password=True)
    db.session.add(user)
    print(f"[seed] 创建管理员账号 {ADMIN_USERNAME}（初始密码：{ADMIN_INITIAL_PASSWORD}，首次登录强制修改）")


def seed_configs():
    for key, value, vtype, desc in DEFAULT_CONFIGS:
        if SystemConfig.query.filter_by(key=key).first():
            continue
        db.session.add(SystemConfig(key=key, value_json=json.dumps(value,
                                                                   ensure_ascii=False),
                                    value_type=vtype, description=desc))
    print(f"[seed] 系统配置默认值已就绪（{len(DEFAULT_CONFIGS)} 项）")


def seed_scales():
    created = 0
    for meta in SCALES:
        scale = Scale.query.filter_by(abbreviation=meta["abbreviation"]).first()
        if scale is None:
            scale = Scale(
                name_zh=meta["name_zh"], name_en=meta["name_en"],
                abbreviation=meta["abbreviation"], source=meta["source"],
                description=meta["description"],
                target_population=meta["target_population"],
                estimated_minutes=meta["estimated_minutes"],
                status="active",
                license_status="unauthorized",
            )
            db.session.add(scale)
            db.session.flush()
            created += 1
        if scale.items.count() == 0:
            for item_number, text, options, is_reversed, dim in meta["items"]:
                db.session.add(ScaleItem(
                    scale_id=scale.id, item_number=item_number, item_text=text,
                    options_json=json.dumps(options, ensure_ascii=False),
                    is_reversed=is_reversed, dimension=dim, sort_order=item_number))
    db.session.flush()
    print(f"[seed] 量表就绪：{len(SCALES)} 个（新建 {created} 个）")


def seed_packages():
    created = 0
    for meta in PACKAGES:
        pkg = ScalePackage.query.filter_by(name=meta["name"]).first()
        if pkg is None:
            pkg = ScalePackage(name=meta["name"], description=meta["description"],
                               estimated_time_minutes=meta["estimated_time_minutes"],
                               scale_ids_json="[]", status="active")
            db.session.add(pkg)
            db.session.flush()
            created += 1
        entries = json.loads(pkg.scale_ids_json or "[]")
        existing = {e.get("scale_id") for e in entries}
        order = len(entries)
        for abbr in meta["scales"]:
            scale = Scale.query.filter_by(abbreviation=abbr).first()
            if scale and scale.id not in existing:
                order += 1
                entries.append({"scale_id": scale.id, "order": order})
        pkg.scale_ids_json = json.dumps(entries, ensure_ascii=False)
    db.session.flush()
    print(f"[seed] 组合包就绪：{len(PACKAGES)} 个（新建 {created} 个）")


def seed_push_rules():
    created = 0
    for meta in PUSH_RULES:
        if PushRule.query.filter_by(name=meta["name"]).first():
            continue
        pkg = ScalePackage.query.filter_by(name=meta["package"]).first()
        if pkg is None:
            continue
        db.session.add(PushRule(
            name=meta["name"], priority=meta["priority"],
            condition_json=json.dumps(meta["conditions"], ensure_ascii=False),
            package_id=pkg.id, status="active"))
        created += 1
    db.session.flush()
    print(f"[seed] 推送规则就绪（新建 {created} 条）")


def seed_referral_rules():
    created = 0
    for meta in REFERRAL_RULES:
        if ReferralRule.query.filter_by(name=meta["name"]).first():
            continue
        scale = Scale.query.filter_by(abbreviation=meta["scale"]).first()
        if scale is None:
            continue
        cond = [{"scale_id": scale.id, "dimension": meta["dimension"],
                 "op": meta["op"], "value": meta["value"]}]
        db.session.add(ReferralRule(
            name=meta["name"], priority=meta["priority"],
            condition_json=json.dumps(cond, ensure_ascii=False),
            output_label_doctor=meta["doctor"],
            output_label_parent=meta["parent"],
            output_style=meta["style"], output_tags=meta["tags"],
            status="active"))
        created += 1
    db.session.flush()
    print(f"[seed] 分科规则就绪（新建 {created} 条）")


def seed_norms():
    created = 0
    for meta in NORMS:
        scale = Scale.query.filter_by(abbreviation=meta["scale"]).first()
        if scale is None:
            continue
        if Norm.query.filter_by(scale_id=scale.id, dimension="total",
                                status="active").first():
            continue
        db.session.add(Norm(
            scale_id=scale.id, dimension="total", population_group="全人群",
            sample_size=None,
            source="种子数据近似值，正式上线前需专业审定",
            mean=meta["mean"], std_dev=meta["std_dev"],
            percentiles_json="{}",
            thresholds_json=json.dumps(meta["thresholds"], ensure_ascii=False),
            status="active"))
        created += 1
    db.session.flush()
    print(f"[seed] 常模就绪（新建 {created} 条）")


def main():
    env = "development"
    if "--env" in sys.argv:
        env = sys.argv[sys.argv.index("--env") + 1]

    app = create_app(env)
    with app.app_context():
        seed_admin()
        seed_configs()
        seed_scales()
        seed_packages()
        seed_push_rules()
        seed_referral_rules()
        seed_norms()
        db.session.commit()
        print("[seed] 全部种子数据写入完成。")


if __name__ == "__main__":
    main()
