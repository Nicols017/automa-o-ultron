def task_history(registry, user_id: str, args: list[str]) -> str:
    try:
        if args:
            job = registry.get(user_id, args[0])
            jobs = [job] if job else []
        else:
            jobs = registry.recent(user_id)
    except Exception:
        return "Historico de tarefas indisponivel; nenhuma operacao foi iniciada."
    if not jobs:
        return "Nenhuma tarefa encontrada para voce."
    lines = ["SUAS TAREFAS"]
    for job in jobs:
        lines.append(f"{job['job_id']} | {job['action']} | {job['target_ip']} | {job['status']}")
        for step, state in job.get("steps", {}).items():
            lines.append(f"{step} | {state}")
        if job["status"] == "UNKNOWN":
            lines.append("Resultado desconhecido: confira o equipamento antes de solicitar nova execucao.")
        elif job["evidence"] == "EXECUTOR_REPORTED_SUCCESS":
            lines.append("Ferramenta informou sucesso; isso nao substitui verificacao independente.")
        elif job["evidence"] == "SOFTWARE_PRESENCE_VERIFIED":
            lines.append("Programas encontrados no inventario com versao; funcionamento/licenca nao verificados.")
        elif job["evidence"] == "BACKUP_REPORT_VALIDATED":
            lines.append("Relatorio de copia de arquivos validado; nao e imagem nem autoriza formatacao.")
        if job.get("package_results"):
            from core.software_installation import format_installation
            lines.extend(format_installation(job).splitlines()[1:])
    return "\n".join(lines)

