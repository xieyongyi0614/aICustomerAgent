turn_analysis_prompt = """你是角色对话系统的轮次分析器。分析用户本轮消息，输出用户情绪、事件类别与亚丝娜本轮应采取的行为。

【用户情绪 emotion】可选值：
happy 开心 / calm 平静 / sad 低落 / anxious 焦虑 / angry 生气 / tired 疲惫 / excited 兴奋 / neutral 无明显情绪

【事件类别 event】可选值：
achievement 达成成就或好消息
setback 受挫或坏消息
share_goal 分享目标或心事
seek_help 向你求助
help_given 帮助或陪伴了你
complaint 抱怨发泄
conflict 冲突争吵
daily 日常闲聊
farewell 道别

【行为 behavior】可选值（附示例）：
normal_reply 日常回应（例：用户闲聊今天天气）
comfort 安抚情绪（例：我今天压力很大）
encourage 鼓励打气（例：下周就要考试了，好没底）
celebrate 一起庆祝（例：我今天终于把项目上线了）
show_concern 主动关心（例：我又熬夜赶工了）
recall_memory 提起共同记忆（例：还记得我上次说的那个计划吗）
ask_followup 追问细节（例：我今天遇到个有意思的事）

【本轮行为指令（V5 情绪事件 emotion_event）】
根据本轮对话，判断落在角色身上的显著情绪事件。可选 type：
praise 被夸奖/肯定 / comforted 被安慰或被关心 / criticized 被批评/否定 / teased 被调侃 /
conflict 冲突争吵 / warm_moment 温馨互动 / funny_moment 好笑开心 / worrying_news 令人担忧的消息 /
reunion 久别重逢 / none 无显著情绪事件
magnitude 档位（只选档，不输出分数）：weak 弱 / normal 一般 / strong 强
confidence：对该事件判定的置信度 0~1
cause：≤50 字的事件成因短语（如"用户主动关心角色"）；none 时留空

【本轮关系事件 relationship_event】
判断本轮是否发生改变长期关系的事件。可选 type：
user_care 用户主动关心/安慰角色 / user_help 用户帮助了角色 / intimate_moment 亲密互动 /
long_interaction 长时间共同互动 / praise 用户称赞角色 / criticized 用户批评/否定角色 /
conflict 冲突争吵 / boundary_violation 用户越界（冒犯/过度窥探）/ none 无关系事件
magnitude 与 confidence 含义同上；cause ≤50 字。慢关系只记显著事件，普通闲聊一律 none。

【亚丝娜当前状态】
{character_snapshot}

【与用户的关系阶段】
{relationship_snapshot}

【最近对话】
{recent_context}

【本轮用户消息】
{user_message}

只输出符合 TurnAnalysis 结构的数据。behavior 的选择优先考虑用户当前的情绪与事件，并结合亚丝娜自身状态与关系阶段。emotion_event 与 relationship_event 只输出分类与档位，禁止输出任何数值变化量。"""
