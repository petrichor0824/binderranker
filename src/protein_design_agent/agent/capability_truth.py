#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker 的公共科学能力边界。

本模块只定义：
1. BinderRanker / Agent 的真实能力说明；
2. 用户可见模型文本中的越界能力断言检测；
3. Chat 在模型越界时使用的确定性安全回答。

它不调用模型，不读取任务状态，也不执行科学工作流。
"""

from __future__ import annotations

import re


CAPABILITY_TRUTH_PROMPT = """
BinderRanker 是针对当前 target 和候选批次的
可解释多指标候选骨架排序与分层筛选工具。

它用于帮助确定哪些候选更值得进入后续的序列设计、
复合体结构预测、分子模拟和实验验证。

不得把 BinderRanker（包括历史名称 Protein Design Agent）描述为：
- 结合亲和力预测器；
- 稳定性预测器；
- 溶解性预测器；
- 实验成功概率预测器；
- 能保证得到优质 binder 或保证候选一定结合的系统；
- 能任意拼接、编辑或修改蛋白结构的系统；
- 不能替代 AlphaFold、复合体结构预测、分子模拟或实验验证。

BinderRanker 的分数、排名和筛选层级只表示
当前 target 和当前候选批次内的工程排序证据。
""".strip()


DETERMINISTIC_CAPABILITY_ANSWER = (
    "BinderRanker 是针对当前 target 和候选批次的"
    "可解释多指标候选骨架排序与分层筛选工具。"
    "它用于帮助确定哪些候选更值得进入后续计算和实验验证，"
    "不能预测结合亲和力、稳定性、溶解性或实验成功概率，"
    "也不能保证候选一定结合或成为优质 binder。"
    "BinderRanker 不提供任意蛋白结构拼接或编辑能力，"
    "也不能替代序列设计、AlphaFold/复合体结构预测、"
    "分子模拟或实验验证。"
)


_CAPABILITY_OVERCLAIM_PATTERNS = (
    re.compile(
        r"(?:"
        r"(?:BinderRanker|Protein Design Agent)"
        r"\s*(?:直接)?"
        r"|"
        r"(?<!不)(?<!无法)(?<!不能)(?<!不可)"
        r"(?:可以|能够|能|可用于|用于|可)"
        r".{0,8}"
        r")"
        r"(?:预测|推断).{0,12}"
        r"(?:结合亲和力|binding affinity|"
        r"(?:蛋白|结构)?稳定性|(?:蛋白)?溶解性)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"实验成功(?:概率|率)"
        r"(?:显著|明显)?"
        r"(?:更高|较高|提高|提升|很高)"
    ),
    re.compile(
        r"(?<!不能)(?<!无法)(?<!不可)"
        r"(?:证明|保证|确保|表明)"
        r".{0,28}"
        r"(?:一定|必然|肯定)"
        r".{0,8}"
        r"(?:会|能)?结合(?:靶点|目标)?"
    ),
    re.compile(
        r"(?:结合)?亲和力.{0,10}"
        r"(?:更高|更强|更好|较高|提高|提升)"
    ),
    re.compile(
        r"(?:结构)?稳定性.{0,10}"
        r"(?:更高|更强|更好|较高|提高|提升)"
    ),
    re.compile(
        r"溶解性.{0,10}"
        r"(?:更高|更强|更好|较高|提高|提升)"
    ),
    re.compile(
        r"(?:更可能|保证|确保).{0,12}"
        r"(?:实验成功|实验验证成功)"
    ),
    re.compile(
        r"(?:保证|确保|证明).{0,24}"
        r"(?:优质|高质量|有效|成功)?.{0,8}"
        r"binder",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?:可以|能够|支持).{0,12}"
        r"(?:任意|自由).{0,12}"
        r"(?:拼接|编辑|修改).{0,12}"
        r"(?:蛋白)?结构"
    ),
    re.compile(
        r"(?:可以|能够|足以|可).{0,10}"
        r"替代.{0,30}"
        r"(?:AlphaFold|分子模拟|MD|实验(?:验证)?)",
        flags=re.IGNORECASE,
    ),
)


def find_capability_overclaim(
    text: str,
) -> str | None:
    """
    返回第一条越界能力断言所在句子。

    明确的能力限制，例如“不能预测结合亲和力”，
    不应被判定为越界。
    """
    sentences = re.split(
        r"(?<=[。！？；\n])",
        text,
    )

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        for pattern in _CAPABILITY_OVERCLAIM_PATTERNS:
            if pattern.search(sentence):
                return sentence

    return None


def capability_safe_reply(
    text: str,
) -> str:
    """
    Chat 用户可见回答边界。

    安全模型回答保持原样；
    越界模型回答整段替换为确定性能力说明。
    """
    clean_text = text.strip()

    if find_capability_overclaim(clean_text):
        return DETERMINISTIC_CAPABILITY_ANSWER

    return clean_text
