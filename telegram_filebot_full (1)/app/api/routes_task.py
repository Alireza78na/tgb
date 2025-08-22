from fastapi import APIRouter, HTTPException, status, Depends
from app.core.auth import get_current_user
from app.services.task_queue import task_queue, TaskStatus

router = APIRouter()

@router.get("/{task_id}/status", tags=["Tasks"])
async def get_task_status(task_id: str, user_id: str = Depends(get_current_user)):
    """
    Get the status and result of a background task.
    """
    task = await task_queue.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Ensure users can only query their own tasks
    if task.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return {
        "task_id": task.id,
        "status": task.status.value,
        "result": task.result.result if task.result else None,
        "error": task.result.error if task.result else None,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
    }

@router.post("/{task_id}/cancel", tags=["Tasks"])
async def cancel_task(task_id: str, user_id: str = Depends(get_current_user)):
    """
    Cancel a pending background task.
    """
    task = await task_queue.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if task.status not in [TaskStatus.PENDING, TaskStatus.RETRYING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task with status '{task.status.value}'",
        )

    was_cancelled = await task_queue.cancel_task(task_id)
    if not was_cancelled:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel task",
        )

    return {"message": "Task cancellation request accepted"}
