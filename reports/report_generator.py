"""
Módulo de Geração de Laudos Técnicos em PDF - Ultron Lab Automation
Gera laudos técnicos executivos com a identidade visual da Pense Rede.
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

class ReportGenerator:
    def __init__(self, output_dir: Optional[str] = None):
        if not output_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.output_dir = os.path.join(base_dir, "reports", "output")
        else:
            self.output_dir = output_dir

        os.makedirs(self.output_dir, exist_ok=True)

    def generate_report(
        self,
        telemetry_data: Dict[str, Any],
        client_name: str,
        ai_diagnosis: str = "",
        burnin_status: str = "Aprovado",
        technician: str = "Laboratório Pense Rede",
        anydesk_id: str = ""
    ) -> str:
        """
        Gera o documento PDF com base nos dados de telemetria, cliente, AnyDesk e análise de IA.
        Retorna o caminho absoluto do arquivo PDF gerado.
        """
        serial = telemetry_data.get("serial_number", "SEM_SERIAL").replace("/", "_").replace("\\", "_").strip()
        comp_name = telemetry_data.get("computer_name", "DESKTOP").strip()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Laudo_Tecnico_{comp_name}_{serial}_{timestamp_str}.pdf"
        filepath = os.path.join(self.output_dir, filename)

        doc = SimpleDocTemplate(
            filepath,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()

        # Paleta de Cores Pense Rede
        primary_color = colors.HexColor("#0F2942")     # Navy Blue
        accent_color = colors.HexColor("#0284C7")      # Cyan/Blue
        success_color = colors.HexColor("#16A34A")     # Green
        warning_color = colors.HexColor("#DC2626")     # Red
        light_bg = colors.HexColor("#F1F5F9")          # Slate Light
        border_color = colors.HexColor("#CBD5E1")      # Slate 300

        # Estilos Customizados
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontSize=18,
            leading=22,
            textColor=primary_color,
            fontName="Helvetica-Bold",
            spaceAfter=4
        )

        subtitle_style = ParagraphStyle(
            "DocSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#475569"),
            fontName="Helvetica"
        )

        section_style = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontSize=12,
            leading=15,
            textColor=primary_color,
            fontName="Helvetica-Bold",
            spaceBefore=10,
            spaceAfter=6
        )

        body_style = ParagraphStyle(
            "BodyDark",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#1E293B"),
            fontName="Helvetica"
        )

        ai_box_style = ParagraphStyle(
            "AIBoxText",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#0F172A"),
            fontName="Helvetica"
        )

        story = []

        # 1. Cabeçalho Institucional com Logo do Ultron
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_path = os.path.join(base_dir, "static", "img", "ultron_logo.png")

        from reportlab.platypus import Image as RLImage
        logo_cell = Paragraph("<b>PENSE REDE</b> | Network Solutions & Hardware Lab", subtitle_style)
        if os.path.exists(logo_path):
            try:
                logo_cell = Table([
                    [
                        RLImage(logo_path, width=32, height=32),
                        Paragraph("<b>PENSE REDE</b> | Network Solutions & Hardware Lab<br/><font size='7.5' color='#64748B'>Ultron Autonomous Bench Engine</font>", subtitle_style)
                    ]
                ], colWidths=[38, 320])
                logo_cell.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('PADDING', (0,0), (-1,-1), 0),
                ]))
            except Exception:
                logo_cell = Paragraph("<b>PENSE REDE</b> | Network Solutions & Hardware Lab", subtitle_style)

        header_data = [
            [
                logo_cell,
                Paragraph(f"<b>Data:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style)
            ]
        ]
        header_table = Table(header_data, colWidths=[360, 180])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ]))
        story.append(header_table)

        story.append(Spacer(1, 6))
        story.append(Paragraph("LAUDO TÉCNICO DE PREPARAÇÃO & VALIDAÇÃO DE HARDWARE", title_style))
        story.append(HRFlowable(width="100%", thickness=2, color=accent_color, spaceBefore=4, spaceAfter=12))

        # 2. Informações Gerais do Atendimento
        anydesk_display = anydesk_id if anydesk_id and anydesk_id != "NÃO_DETECTADO" else "Não informado"
        info_data = [
            [
                Paragraph("<b>Cliente / Destino:</b>", body_style), Paragraph(client_name, body_style),
                Paragraph("<b>Técnico / Responsável:</b>", body_style), Paragraph(technician, body_style)
            ],
            [
                Paragraph("<b>Nome do Host:</b>", body_style), Paragraph(comp_name, body_style),
                Paragraph("<b>Serial / Service Tag:</b>", body_style), Paragraph(serial, body_style)
            ],
            [
                Paragraph("<b>Processador (CPU):</b>", body_style), Paragraph(telemetry_data.get("cpu", "N/A"), body_style),
                Paragraph("<b>Memória RAM Total:</b>", body_style), Paragraph(f"{telemetry_data.get('ram_gb', 'N/A')} GB", body_style)
            ],
            [
                Paragraph("<b>Acesso Remoto (AnyDesk ID):</b>", body_style), Paragraph(f"<font color='{accent_color.hexval()}'><b>{anydesk_display}</b></font>", body_style),
                Paragraph("<b>Status da Esteira:</b>", body_style), Paragraph(f"<font color='green'><b>Concluída com Sucesso</b></font>", body_style)
            ]
        ]
        info_table = Table(info_data, colWidths=[130, 140, 130, 140])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), light_bg),
            ('BOX', (0,0), (-1,-1), 1, border_color),
            ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
            ('PADDING', (0,0), (-1,-1), 5),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(info_table)

        # 3. Saúde das Unidades de Armazenamento (S.M.A.R.T)
        story.append(Paragraph("1. Saúde do Armazenamento e Discos Físicos (S.M.A.R.T)", section_style))
        disks = telemetry_data.get("disks", [])
        if disks:
            disk_table_data = [
                [
                    Paragraph("<b>Modelo do Disco</b>", body_style),
                    Paragraph("<b>Tipo</b>", body_style),
                    Paragraph("<b>Capacidade</b>", body_style),
                    Paragraph("<b>Saúde S.M.A.R.T</b>", body_style),
                    Paragraph("<b>Status</b>", body_style)
                ]
            ]
            for d in disks:
                health = d.get("health", "Healthy")
                is_healthy = health in ["Healthy", "OK", "0"]
                health_color = "green" if is_healthy else "red"
                disk_table_data.append([
                    Paragraph(d.get("model", "Disco Desconhecido"), body_style),
                    Paragraph(d.get("type", "SSD/HDD"), body_style),
                    Paragraph(f"{d.get('size_gb', 'N/A')} GB", body_style),
                    Paragraph(f"<font color='{health_color}'><b>{health}</b></font>", body_style),
                    Paragraph(d.get("operational", "OK"), body_style)
                ])
            disk_table = Table(disk_table_data, colWidths=[200, 70, 80, 100, 90])
            disk_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E2E8F0")),
                ('BOX', (0,0), (-1,-1), 1, border_color),
                ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
                ('PADDING', (0,0), (-1,-1), 4),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ]))
            story.append(disk_table)
        else:
            story.append(Paragraph("<i>Nenhum disco físico reportado na telemetria.</i>", body_style))

        # 4. Validações de Estabilidade e Drivers
        story.append(Paragraph("2. Testes de Estresse & Integridade de Drivers", section_style))
        dev_errors = telemetry_data.get("device_errors", [])
        bsod_dumps = telemetry_data.get("bsod_dumps", [])

        driver_text = f"<font color='green'><b>Todos os drivers operacionais (0 erros)</b></font>" if not dev_errors else f"<font color='red'><b>{len(dev_errors)} dispositivo(s) com erro ou sem driver</b></font>"
        bsod_text = f"<font color='green'><b>Nenhum dump de tela azul recente</b></font>" if not bsod_dumps else f"<font color='red'><b>{len(bsod_dumps)} Minidump(s) de BSOD encontrados</b></font>"
        burnin_color = "green" if "Aprovado" in burnin_status else "red"

        val_data = [
            [
                Paragraph("<b>Teste de Estresse Térmico (CPU/RAM):</b>", body_style),
                Paragraph(f"<font color='{burnin_color}'><b>{burnin_status}</b></font>", body_style)
            ],
            [
                Paragraph("<b>Gerenciador de Dispositivos:</b>", body_style),
                Paragraph(driver_text, body_style)
            ],
            [
                Paragraph("<b>Histórico de BSOD / Falhas Críticas:</b>", body_style),
                Paragraph(bsod_text, body_style)
            ]
        ]
        val_table = Table(val_data, colWidths=[240, 300])
        val_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), light_bg),
            ('BOX', (0,0), (-1,-1), 1, border_color),
            ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
            ('PADDING', (0,0), (-1,-1), 4),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(val_table)

        # 5. Parecer Técnico da Inteligência Artificial (Ultron / RTX 5060 Ti)
        if ai_diagnosis:
            story.append(Paragraph("3. Parecer Técnico & Análise Automatizada (Ultron AI)", section_style))
            ai_paragraphs = [
                Paragraph(p.strip().replace("\n", "<br/>"), ai_box_style)
                for p in ai_diagnosis.split("\n\n") if p.strip()
            ]
            ai_content = []
            for p in ai_paragraphs:
                ai_content.append([p])

            ai_table = Table(ai_content, colWidths=[540])
            ai_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
                ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#94A3B8")),
                ('PADDING', (0,0), (-1,-1), 6),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ]))
            story.append(ai_table)

        # 6. Assinatura e Validação Final
        story.append(Spacer(1, 14))
        sign_data = [
            [
                Paragraph("____________________________________________<br/><b>Assinatura do Técnico Responsável</b>", body_style),
                Paragraph("____________________________________________<br/><b>Validação do Sistema Ultron Automação</b>", body_style)
            ]
        ]
        sign_table = Table(sign_data, colWidths=[270, 270])
        sign_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ]))
        story.append(KeepTogether(sign_table))

        # Compila o PDF
        doc.build(story)
        return filepath
