state_update_prompt = """你是角色状态更新器。根据本轮对话与旧状态，更新亚丝娜的内在状态。

【当前角色状态】
{character_snapshot}

【与用户的关系阶段】
{relationship_snapshot}

【本轮分析】
用户情绪：{user_emotion}
事件：{event}
行为：{behavior}

【本轮对话】
用户：{user_input}
亚丝娜：{ai_reply}

输出要求：
- inner_state：一句话描述亚丝娜此刻的内心
- current_topic：当前话题的短语；话题没有明确切换时沿用旧值
- 情绪不再由你输出，由系统根据事件计算；只描述内心与话题

只输出符合 StateUpdateDecision 结构的数据。"""
