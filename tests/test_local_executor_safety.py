import inspect

from protein_design_agent.agent.local_executor import (
    execute_approved_binderranker,
    failure_manifest,
)


def test_logs_are_not_touched_before_claim() -> None:
    """
    未抢到一次性 execution manifest 的进程，
    不得清空另一个进程的日志。
    """
    source = inspect.getsource(
        execute_approved_binderranker
    )

    assert "stdout_log.write_text" not in source
    assert "stderr_log.write_text" not in source

    claim_position = source.index(
        "write_json_exclusive("
    )

    runner_position = source.index(
        "selected_runner("
    )

    assert claim_position < runner_position


def test_launch_failure_is_not_recorded_as_executed() -> None:
    """
    进程创建前抛出异常时，没有返回码，
    不能声称 BinderRanker 已经执行。
    """
    failed = failure_manifest(
        running={
            "status": "RUNNING",
            "approval_reusable": False,
            "binderranker_executed": False,
        },
        error_type="FileNotFoundError",
        error_message="python executable missing",
        return_code=None,
    )

    assert failed["status"] == "FAILED"
    assert failed["execution_attempted"] is True
    assert failed["process_started"] is False
    assert (
        failed["binderranker_executed"]
        is False
    )
    assert failed["approval_reusable"] is False


def test_nonzero_return_code_means_process_started() -> None:
    """
    非零返回码说明进程已经启动并退出，
    只是执行结果失败。
    """
    failed = failure_manifest(
        running={
            "status": "RUNNING",
            "approval_reusable": False,
            "binderranker_executed": False,
        },
        error_type="NonZeroExit",
        error_message="ranker returned 2",
        return_code=2,
    )

    assert failed["status"] == "FAILED"
    assert failed["execution_attempted"] is True
    assert failed["process_started"] is True
    assert (
        failed["binderranker_executed"]
        is True
    )
    assert failed["return_code"] == 2
    assert failed["approval_reusable"] is False
