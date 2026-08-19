"""llm services"""

import time

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.modules.llm.config import build_asuna_system_message, role_router_prompt
from app.modules.llm.models import RoleMode


async def llm_chat_open_ai(content: str = "介绍一下你自己"):
    print("执行中：")

    start = time.perf_counter()
    try:
        llm = ChatOpenAI(
            model="LongCat-2.0",
            api_key="ak_2UC9hE04C9iL8E51pc5K92hO4st4Z",
            base_url="https://api.longcat.chat/openai/v1",
            temperature=0.9,  # 核心：情感与创造力
            top_p=0.92,  # 多样性控制
            frequency_penalty=0.4,  # 避免重复句式
            presence_penalty=0.5,  # 鼓励新话题/细节
            max_tokens=50,  # 限制单次回复长度，模拟真实对话
            extra_body={"thinking": {"type": "disabled"}},
        )
        router = llm.with_structured_output(RoleMode)
        # result: RoleMode = router.invoke(
        #     role_router_prompt.format(user_message=content)
        # )
        role_prompt = ChatPromptTemplate.from_messages(
            [("system", role_router_prompt.format(user_message=content))]
        )
        role_router_chain = role_prompt | router
        result: RoleMode = role_router_chain.invoke({"user_message": content})

        role_router_time = time.perf_counter() - start
        print(f"\nroleRouter 耗时: {role_router_time:.2f}s")
        print("result", result)

        system_message = build_asuna_system_message(result.mode)

        chat_prompt = ChatPromptTemplate.from_messages(
            [("system", system_message.content), ("human", "{content}")]
        )

        answer_chain = chat_prompt | llm

        # messages = chat_prompt.invoke({"content": content}).to_messages()

        first_chunk = True
        for chunk in answer_chain.stream({"content": content}):
            if first_chunk:
                print(f"\n首 token 耗时: {time.perf_counter() - start:.2f}s")
                first_chunk = False
            print(chunk.content, end="")

        print(f"\n生成总耗时: {time.perf_counter() - start:.2f}s")
        print("\n")
        ## 一次性等待
        # response = await llm.ainvoke("你是一个电商客服，请介绍一下你的职责")
        # print(response.content)
    except Exception as ex:
        print("报错了" + str(ex))
