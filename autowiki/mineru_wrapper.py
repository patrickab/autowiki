import logging
from pathlib import Path


log = logging.getLogger(__name__)


async def parse_pdf(pdf_path: str | Path, out_dir: str | Path, backend: str = "pipeline") -> Path:
    from mineru.cli import api_client

    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if backend == "auto":
        backend = _detect_backend()
    log.info("MinerU using backend: %s", backend)

    form_data = api_client.build_parse_request_form_data(
        lang_list=["en"],
        backend=backend,
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
        server_url=None,
        start_page_id=0,
        end_page_id=None,
        return_md=True,
        return_middle_json=False,
        return_model_output=False,
        return_content_list=False,
        return_images=True,
        response_format_zip=True,
        return_original_file=False,
    )
    assets = [api_client.UploadAsset(path=pdf_path, upload_name=pdf_path.name)]

    import httpx

    local = api_client.LocalAPIServer()
    base_url = local.start()
    async with httpx.AsyncClient(timeout=api_client.build_http_timeout()) as cli:
        try:
            await api_client.wait_for_local_api_ready(cli, local)
            sub = await api_client.submit_parse_task(base_url, assets, form_data)
            await api_client.wait_for_task_result(cli, sub, task_label=pdf_path.name)
            zp = await api_client.download_result_zip(cli, sub, task_label=pdf_path.name)
            api_client.safe_extract_zip(zp, out_dir)
            zp.unlink(missing_ok=True)
        finally:
            local.stop()

    md_files = sorted(out_dir.glob("**/*.md"), key=lambda p: len(p.name))
    if not md_files:
        raise RuntimeError(f"MinerU produced no .md output in {out_dir}")
    return md_files[0]


def _detect_backend() -> str:
    import torch
    if torch.cuda.is_available():
        return "hybrid-auto-engine"
    return "pipeline"
