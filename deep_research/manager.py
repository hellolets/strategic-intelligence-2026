"""
Módulo Manager: Gestión de ejecución asíncrona de grafos.
"""
import os
import asyncio
from typing import List, Dict, Any, Tuple
from pyairtable import Table

from .state import ResearchState
from .graph import create_research_graph
from .logger import logger
from .config import items_table, airtable_base, MAX_RESULTS_PER_QUERY, proyectos_table, CONCURRENCY_LIMIT
from .utils import extract_urls_from_sources
# COMPANY_CONTEXT ya no se importa - se usa contexto de Airtable

class ResearchManager:
    def __init__(self, concurrency_limit: int = CONCURRENCY_LIMIT):
        self.concurrency_limit = concurrency_limit
        self.semaphore = None  # Se creará dentro del loop de eventos
        self.graph = create_research_graph()
        self.items_table = items_table
        self.proyectos_table = proyectos_table
        self.running = True
        self._agent_cache = {} # Cache para evitar re-consultar System_Prompts
        self._metrics_accumulator = []  # Acumulador para métricas de todos los reportes

    async def process_item(self, record: Dict[str, Any]):
        """Procesa un único item usando el grafo."""
        # Asegurar que el semáforo existe (por si se llama antes de run_loop)
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        record_id = record['id']
        fields = record.get('fields', {})
        topic = fields.get('Topic', fields.get('Tema', fields.get('Title', 'Sin tema')))
        
        async with self.semaphore:
            logger.log_section(f"Procesando Item: {topic}", f"ID: {record_id}")
            loop = asyncio.get_running_loop()
            
            # 1. Preparar estado inicial (Getting context)
            try:
                # Update síncrono en executor
                await loop.run_in_executor(None, lambda: self.items_table.update(record_id, {"Status": "Getting context"}))
            except Exception as e:
                logger.log_error(f"Error actualizando status a 'Getting context' para {record_id}: {e}")

            # 1.5. Preparar estado inicial (esto puede lanzar ValueError si no hay contexto)
            try:
                # _prepare_initial_state puede ser lento (I/O Airtable, parsing), correr en executor
                initial_state = await loop.run_in_executor(None, self._prepare_initial_state, record)
            except ValueError as context_error:
                # Error específico de contexto faltante - marcar como Error y detener
                error_msg = str(context_error)
                logger.log_error(f"❌ {error_msg}")
                try:
                    await loop.run_in_executor(None, lambda: self.items_table.update(record_id, {
                        "Status": "Error",
                        "Final_Report": f"Error: {error_msg}"
                    }))
                except Exception as update_err:
                    logger.log_error(f"Error actualizando status a Error para {record_id}: {update_err}")
                return  # Detener procesamiento
            
            # 2. Actualizar estado a Processing (Investigación iniciada)
            try:
                await loop.run_in_executor(None, lambda: self.items_table.update(record_id, {"Status": "Processing"}))
            except Exception as e:
                logger.log_error(f"Error actualizando status a 'Processing' para {record_id}: {e}")
                return

            # 3. Ejecutar grafo
            try:
                # Como el grafo ahora tiene nodos async (evaluator), debemos usar ainvoke
                # invoke es síncrono y fallará con nodos async.
                # Calcular recursion_limit para evitar errores en loops largos
                # Usar max_retries dinámico según report_type
                from .config import MAX_RETRIES, get_dynamic_config
                report_type = initial_state.get('report_type', initial_state.get('prompt_type', None))
                dynamic_config = get_dynamic_config(report_type)
                max_retries = dynamic_config.get('max_retries', MAX_RETRIES)
                recursion_limit = (max_retries * 6) + 10  # Margen de seguridad
                
                final_state = await self.graph.ainvoke(
                    initial_state, 
                    config={"recursion_limit": recursion_limit}
                )
                
                # 4. Guardar resultados
                # _save_results hace writes a Airtable y I/O local, correr en executor
                await loop.run_in_executor(None, self._save_results, record_id, final_state)
                logger.log_success(f"Completado: {topic}")
                
            except Exception as e:
                import traceback
                error_msg = str(e) if e else "Error desconocido (excepción sin mensaje)"
                error_traceback = traceback.format_exc()
                logger.log_error(f"Error ejecutando grafo para {record_id}: {error_msg}")
                logger.log_error(f"Traceback completo:\n{error_traceback}")
                # Log detallado para debugging
                logger.log_error(f"ERROR DETALLADO ejecutando grafo para {record_id}:")
                logger.log_info(f"Mensaje: {error_msg}")
                logger.log_info(f"Tipo: {type(e).__name__}")
                if error_traceback:
                    logger.log_info(f"Traceback:\n{error_traceback}")
                try:
                    await loop.run_in_executor(None, lambda: self.items_table.update(record_id, {
                        "Status": "Error", 
                        "Final_Report": f"Error fatal en ejecución: {error_msg}"
                    }))
                except Exception as update_err:
                    logger.log_error(f"Error actualizando status a Error para {record_id}: {update_err}")


    async def process_item_by_id(self, record_id: str):
        """Procesa un item dado su ID (usado por Webhooks)."""
        try:
            # Ejecutar fetch en executor para no bloquear
            loop = asyncio.get_running_loop()
            record = await loop.run_in_executor(None, lambda: self.items_table.get(record_id))
            
            if not record:
                logger.log_error(f"No se encontró el registro {record_id}")
                return
                
            await self.process_item(record)
            
        except Exception as e:
            logger.log_error(f"Error procesando webhook para {record_id}: {e}")

    def _get_system_prompt_and_description(self, fields: Dict[str, Any]) -> Tuple[str, str]:
        """
        Obtiene el System Prompt y la Descripción del Agente desde Airtable.
        Puede venir:
        1. De la referencia System_Prompt_ID (tabla System_Prompts) - Prioridad 1
        2. Del campo System_Prompt directo en el registro - Prioridad 2
        
        Retorna: (system_prompt, agent_description)
        """
        system_prompt = ""
        agent_description = ""

        # 1. Intentar obtener desde System_Prompt_ID (tabla System_Prompts)
        prompt_id = fields.get('System_Prompt_ID')
        if prompt_id:
            # Si es una lista, tomar el primero
            if isinstance(prompt_id, list):
                prompt_id = prompt_id[0]
            
            try:
                # Usar cache si está disponible
                if prompt_id in self._agent_cache:
                    system_prompt, agent_description = self._agent_cache[prompt_id]
                    print(f"   ✅ System Prompt recuperado desde cache (ID: {prompt_id})")
                else:
                    # Obtener nombre de la tabla de prompts desde config.toml via config.py
                    from .config import airtable_base, TOML_CONFIG
                    prompts_table_name = TOML_CONFIG.get("airtable", {}).get("prompts_table_name", "System_Prompts")
                    prompts_table = airtable_base.table(prompts_table_name)
                
                    prompt_record = prompts_table.get(prompt_id)
                    if prompt_record and "fields" in prompt_record:
                        pfields = prompt_record["fields"]
                    
                        # Verificar si está activo
                        is_active = pfields.get("Active", True)
                        if not is_active:
                            print(f"   ⚠️ Agente '{pfields.get('Prompt_Name', 'unknown')}' está inactivo")
                    
                        # Recuperar Prompt
                        system_prompt = pfields.get("System_Prompt") or pfields.get("Prompt") or ""
                    
                        # Recuperar Descripción
                        agent_description = pfields.get("Description") or pfields.get("Descripción") or ""
                    
                        # Log del tipo de agente (buscar Type o Category)
                        agent_type = pfields.get("Type") or pfields.get("Category", "General")
                        agent_name = pfields.get("Prompt_Name", "Unknown")
                        print(f"   🎯 Agente: {agent_name} (Tipo: {agent_type})")
                    
                        # Store in cache
                        if system_prompt:
                            self._agent_cache[prompt_id] = (system_prompt, agent_description)
                        
            except Exception as e:
                logger.log_warning(f"Error recuperando System Prompt/Descripción desde Airtable: {e}")

        # 2. Fallback al campo de texto directo si existe para el prompt
        if not system_prompt:
             system_prompt = fields.get('System_Prompt') or fields.get('Prompt') or ""
             
        return system_prompt, agent_description
        
    def _get_system_prompt(self, fields: Dict[str, Any]) -> str:
        """Wrapper legacy para compatibilidad."""
        p, _ = self._get_system_prompt_and_description(fields)
        return p

    def _optimize_sources_history(self, sources_text: str, max_chars: int = 85000) -> str:
        """
        Optimiza el historial de fuentes manteniendo las rondas recientes completas
        y resumiendo las antiguas para evitar exceder el límite de Airtable.
        
        Args:
            sources_text: Texto completo del historial de fuentes
            max_chars: Límite máximo de caracteres a mantener
        
        Returns:
            Historial optimizado
        """
        if len(sources_text) <= max_chars:
            return sources_text
        
        # Dividir por rondas (separador: "--- NUEVA RONDA" o "--- PRIMERA RONDA")
        import re
        rounds = re.split(r'--- (?:NUEVA|PRIMERA) RONDA \(', sources_text)
        
        if len(rounds) <= 1:
            # No hay rondas claras, truncar simple pero manteniendo el final
            keep_chars = max_chars - 100  # Margen para mensaje
            return f"...[HISTORIAL OPTIMIZADO: Se mantuvieron los últimos {keep_chars:,} caracteres de {len(sources_text):,} totales]...\n\n{sources_text[-keep_chars:]}"
        
        # Reconstruir rondas con sus timestamps
        reconstructed_rounds = []
        for i, round_content in enumerate(rounds):
            if i == 0:
                # Primera parte (antes de la primera ronda)
                if round_content.strip():
                    reconstructed_rounds.append(("pre", round_content))
                continue
            
            # Extraer timestamp y contenido
            timestamp_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\) ---', round_content)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                content = round_content[timestamp_match.end():].strip()
                round_type = "PRIMERA" if i == 1 and not reconstructed_rounds else "NUEVA"
                reconstructed_rounds.append((timestamp, content, round_type))
            else:
                # Si no hay timestamp, tratar como contenido suelto
                if round_content.strip():
                    reconstructed_rounds.append(("unknown", round_content))
        
        # Estrategia: Mantener las últimas 3-5 rondas completas, resumir las anteriores
        # Calcular cuántas rondas completas podemos mantener
        total_length = 0
        rounds_to_keep_full = []
        rounds_to_summarize = []
        
        # Empezar desde el final (rondas más recientes)
        for i in range(len(reconstructed_rounds) - 1, -1, -1):
            round_data = reconstructed_rounds[i]
            if round_data[0] == "pre":
                # Contenido previo, mantenerlo si cabe
                content = round_data[1]
                if total_length + len(content) < max_chars * 0.3:  # Máximo 30% para contenido previo
                    rounds_to_keep_full.insert(0, round_data)
                    total_length += len(content)
                continue
            
            timestamp = round_data[0]
            content = round_data[1] if len(round_data) > 1 else ""
            round_type = round_data[2] if len(round_data) > 2 else "NUEVA"
            
            # Intentar mantener esta ronda completa
            round_header = f"--- {round_type} RONDA ({timestamp}) ---\n\n"
            round_full = round_header + content
            
            if total_length + len(round_full) < max_chars * 0.7:  # Mantener hasta 70% del límite para rondas completas
                rounds_to_keep_full.insert(0, (timestamp, content, round_type))
                total_length += len(round_full)
            else:
                # Resumir esta ronda y las anteriores
                rounds_to_summarize.insert(0, (timestamp, content, round_type))
        
        # Construir resultado
        result_parts = []
        
        # Agregar mensaje de optimización si hay rondas resumidas
        if rounds_to_summarize:
            total_rounds = len(rounds_to_summarize)
            result_parts.append(f"...[HISTORIAL OPTIMIZADO: {total_rounds} ronda(s) antigua(s) resumida(s) para cumplir límite de Airtable]...\n\n")
            
            # Resumir rondas antiguas: solo URLs y metadatos esenciales
            summarized_urls = set()
            for timestamp, content, round_type in rounds_to_summarize:
                # Extraer URLs de esta ronda
                urls = extract_urls_from_sources(content)
                summarized_urls.update(urls)
            
            if summarized_urls:
                result_parts.append("--- RONDAS ANTIGUAS (resumidas) ---\n")
                result_parts.append(f"URLs procesadas en {total_rounds} ronda(s) anterior(es): {len(summarized_urls)} URL(s) única(s)\n")
                result_parts.append("\n".join(f"- {url}" for url in sorted(summarized_urls)[:50]))  # Máximo 50 URLs
                if len(summarized_urls) > 50:
                    result_parts.append(f"\n... y {len(summarized_urls) - 50} URL(s) más")
                result_parts.append("\n\n")
        
        # Agregar contenido previo si existe
        for round_data in rounds_to_keep_full:
            if round_data[0] == "pre":
                result_parts.append(round_data[1])
                if not round_data[1].endswith("\n\n"):
                    result_parts.append("\n\n")
        
        # Agregar rondas completas mantenidas
        for round_data in rounds_to_keep_full:
            if round_data[0] != "pre":
                timestamp, content, round_type = round_data
                result_parts.append(f"--- {round_type} RONDA ({timestamp}) ---\n\n")
                result_parts.append(content)
                if not content.endswith("\n\n"):
                    result_parts.append("\n\n")
        
        result = "".join(result_parts)
        
        # Verificar que no exceda el límite (con margen de seguridad)
        if len(result) > max_chars:
            # Si aún excede, truncar más agresivamente pero manteniendo estructura
            keep_chars = max_chars - 200  # Margen para mensajes
            result = result[-keep_chars:]
            result = f"...[HISTORIAL TRUNCADO ADICIONALMENTE]...\n\n{result}"
        
        return result

    def _save_results(self, record_id: str, state: ResearchState):
        if state.get("error"):
            self.items_table.update(record_id, {
                "Status": "Error",
                "Final_Report": f"Error: {state['error']}"
            })
            return

        updated_sources = state.get("updated_sources_text", "")
        final_report = state.get("final_report", "")
        
        # Debug logging para verificar valores
        print(f"   📝 Estado final recibido:")
        print(f"      - Final_Report length: {len(final_report)} caracteres")
        print(f"      - Updated_Sources length: {len(updated_sources)} caracteres")
        if not final_report:
            logger.log_warning("⚠️ Final_Report está vacío en el estado final")
        if not updated_sources:
            logger.log_warning("⚠️ Updated_Sources está vacío en el estado final")
        
        # AIRTABLE LIMIT SAFETY: Optimizar historial si excede 85,000 chars (límite es ~100k)
        # Estrategia: Mantener rondas recientes completas, resumir rondas antiguas
        if len(updated_sources) > 85000:
            original_length = len(updated_sources)
            logger.log_warning(f"📦 Optimizando historial de fuentes para {record_id} ({original_length:,} > 85,000 chars)")
            updated_sources = self._optimize_sources_history(updated_sources, max_chars=85000)
            optimized_length = len(updated_sources)
            reduction = original_length - optimized_length
            logger.log_info(f"   ✅ Historial optimizado: {original_length:,} → {optimized_length:,} chars (reducción: {reduction:,} chars, {reduction/original_length*100:.1f}%)")
            
        update_data = {
            "Status": "Done",
            "Final_Report": final_report,
            "Fuentes_Acumuladas": updated_sources
        }
        
        # NOTA: NO se genera DOCX por cada item individual
        # El DOCX solo se genera cuando se consolida el proyecto completo
        # en consolidate_specific_project() (processor.py)
        
        # Generar informe de métricas antes de guardar
        metrics_report = ""
        topic = state.get('topic', 'Sin tema')
        try:
            from .report_metrics import generate_execution_metrics_report
            from .evaluator import print_mimo_judge_metrics
            metrics_report = generate_execution_metrics_report(state, topic)
            print(f"   📊 Informe de métricas generado ({len(metrics_report)} caracteres)")
            
            # Imprimir métricas MiMo vs Gemini
            print_mimo_judge_metrics()
            
            # Acumular métricas en lugar de guardar individualmente
            # Se generará un reporte consolidado al final de la ejecución
            try:
                # Guardar métricas individuales en el acumulador
                self._metrics_accumulator.append({
                    "topic": topic,
                    "metrics_report": metrics_report,
                    "state": state,
                    "record_id": record_id
                })
                print(f"   📊 Métricas acumuladas para reporte consolidado")
                
            except Exception as e:
                logger.log_warning(f"Error acumulando métricas: {e}")
                import traceback
                traceback.print_exc()
            
        except Exception as e:
            logger.log_warning(f"Error generando informe de métricas: {e}")
            import traceback
            traceback.print_exc()
        
        # NOTA: El reporte de métricas NO se guarda en Airtable, solo localmente en reports/
        # El reporte consolidado se genera al final de la ejecución en _generate_consolidated_metrics_report()
        
        # Sources Count
        # Extraer URLs para contar el total real acumulado (SOLO ACEPTADAS)
        try:
            from .utils import extract_urls_from_sources, extract_rejected_urls_from_sources
            all_urls = extract_urls_from_sources(updated_sources)
            rejected_urls = extract_rejected_urls_from_sources(updated_sources)
            
            # El count real son todas las encontradas menos las marcadas como RECHAZADA
            accepted_urls = all_urls - rejected_urls
            update_data["Sources_Count"] = len(accepted_urls)
        except Exception as e:
            logger.log_warning(f"Error calculando Sources_Count: {e}")
            
        # Token Usage (Opcional - solo si el campo existe en Airtable)
        # No incluimos Tokens_window_used por defecto para evitar errores si el campo no existe
        # Asegurarse de que NO se añada Tokens_window_used aunque venga en el state
        if "Tokens_window_used" in update_data:
            del update_data["Tokens_window_used"]
        
        # Calcular costos por agente y total
        try:
            from .cost_calculator import calculate_total_cost_from_state, calculate_costs_by_role_from_state
            
            # Calcular costos individuales por rol
            costs_by_role = calculate_costs_by_role_from_state(state)
            
            # Mapear roles a nombres de campos en Airtable
            role_to_field = {
                "planner": "Planner_Cost",
                "judge": "Judge_Cost",
                "analyst": "Analyst_Cost",
                "plotter": "Plotter_Cost", # Corregido de "plotter" a "ploter"
                "extractor": "Extractor_Cost", # Nuevo campo para el extractor
                "verifier": "Verifier_Cost" # Nuevo campo para el verifier
            }
            
            # Añadir costos individuales al update_data
            for role, cost in costs_by_role.items():
                field_name = role_to_field.get(role)
                if field_name and cost > 0:
                    update_data[field_name] = round(cost, 6)
                    logger.log_info(f"💰 {role.capitalize()}: ${cost:.6f}")
            
            # Calcular y guardar Total_Cost (suma de los 4 campos)
            total_cost = calculate_total_cost_from_state(state)
            if total_cost > 0:
                update_data["Total_Cost"] = round(total_cost, 6)
                logger.log_info(f"💰 Total Cost: ${total_cost:.6f}")
        except Exception as e:
            logger.log_warning(f"Error calculando costos: {e}")
            import traceback
            traceback.print_exc()
        
        # Actualizar registro en Airtable
        try:
            self.items_table.update(record_id, update_data)
            logger.log_success(f"✅ Resultados guardados en Airtable para {record_id}")
        except Exception as e:
            error_str = str(e)
            # Si el error es por campo desconocido, intentar sin campos opcionales
            if "UNKNOWN_FIELD_NAME" in error_str:
                logger.log_warning(f"⚠️ Campo desconocido en Airtable. Reintentando sin campos opcionales...")
                # Remover campos opcionales y reintentar con solo campos esenciales
                safe_update_fields = {
                    "Status": update_data.get("Status", "Done"),
                    "Final_Report": update_data.get("Final_Report", ""),
                    "Fuentes_Acumuladas": update_data.get("Fuentes_Acumuladas", ""),
                }
                
                # Campos opcionales que pueden no existir (Metrics_Report no se guarda en Airtable, solo localmente)
                optional_fields = ["Sources_Count", "Planner_Cost", "Judge_Cost", 
                                 "Analyst_Cost", "Plotter_Cost", "Extractor_Cost", "Verifier_Cost", "Total_Cost"]
                
                # Intentar agregar campos opcionales solo si existen en update_data
                for field in optional_fields:
                    if field in update_data:
                        safe_update_fields[field] = update_data[field]
                
                try:
                    self.items_table.update(record_id, safe_update_fields)
                    logger.log_success(f"✅ Resultados guardados en Airtable (sin campos opcionales desconocidos) para {record_id}")
                except Exception as e2:
                    logger.log_error(f"❌ Error guardando resultados (intento con campos seguros): {e2}")
                    import traceback
                    traceback.print_exc()
            else:
                logger.log_error(f"❌ Error guardando resultados en Airtable: {e}")
                import traceback
                traceback.print_exc()

    def _generate_consolidated_metrics_report(self):
        """Genera un reporte consolidado de métricas de todos los reportes procesados.
        
        Returns:
            float: Costo total de todos los reportes procesados en dólares
        """
        if not self._metrics_accumulator:
            logger.log_info("No hay métricas acumuladas para generar reporte consolidado")
            return 0.0
        
        try:
            import os
            from pathlib import Path
            from datetime import datetime
            
            # Crear carpeta reports/ si no existe
            project_root = Path(__file__).parent.parent
            reports_dir = project_root / "reports"
            reports_dir.mkdir(exist_ok=True)
            
            # Crear nombre de archivo con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"metrics_consolidado_{timestamp}.md"
            metrics_file_path = reports_dir / filename
            
            # Calcular métricas consolidadas
            total_reports = len(self._metrics_accumulator)
            total_cost = 0
            total_tokens = 0
            total_sources = 0
            total_validated_sources = 0
            
            # Generar reporte consolidado en Markdown
            report_lines = [
                f"# Reporte Consolidado de Métricas",
                f"",
                f"**Fecha de Generación:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"**Total de Reportes Procesados:** {total_reports}",
                f"",
                f"---",
                f"",
            ]
            
            # Resumen ejecutivo
            report_lines.extend([
                f"## 📊 Resumen Ejecutivo",
                f"",
            ])
            
            # Acumular totales
            for item in self._metrics_accumulator:
                state = item["state"]
                from .cost_calculator import calculate_total_cost_from_state
                cost = calculate_total_cost_from_state(state)
                total_cost += cost
                
                tokens_by_role = state.get('tokens_by_role', {})
                tokens = sum(tokens_by_role.values())
                total_tokens += tokens
                
                validated = state.get('validated_sources', [])
                total_validated_sources += len(validated)
                total_sources += len(state.get('found_sources', []))
            
            report_lines.extend([
                f"- **Costo Total:** ${total_cost:.6f}",
                f"- **Tokens Totales:** {total_tokens:,}",
                f"- **Fuentes Validadas Total:** {total_validated_sources}",
                f"- **Fuentes Encontradas Total:** {total_sources}",
                f"- **Costo Promedio por Reporte:** ${(total_cost / total_reports):.6f}",
                f"- **Tokens Promedio por Reporte:** {total_tokens // total_reports:,}",
                f"",
                f"---",
                f"",
            ])
            
            # Detalle por reporte
            report_lines.extend([
                f"## 📋 Detalle por Reporte",
                f"",
            ])
            
            for i, item in enumerate(self._metrics_accumulator, 1):
                topic = item["topic"]
                state = item["state"]
                from .cost_calculator import calculate_total_cost_from_state
                cost = calculate_total_cost_from_state(state)
                tokens_by_role = state.get('tokens_by_role', {})
                tokens = sum(tokens_by_role.values())
                validated_count = len(state.get('validated_sources', []))
                
                report_lines.extend([
                    f"### {i}. {topic}",
                    f"",
                    f"- **Costo:** ${cost:.6f}",
                    f"- **Tokens:** {tokens:,}",
                    f"- **Fuentes Validadas:** {validated_count}",
                    f"- **Record ID:** {item['record_id']}",
                    f"",
                ])
            
            report_lines.extend([
                f"---",
                f"",
                f"## 📊 Métricas Detalladas por Reporte",
                f"",
            ])
            
            # Agregar métricas individuales completas
            for i, item in enumerate(self._metrics_accumulator, 1):
                topic = item["topic"]
                metrics_report = item["metrics_report"]
                
                report_lines.extend([
                    f"---",
                    f"",
                    f"## Reporte {i}: {topic}",
                    f"",
                    metrics_report,
                    f"",
                ])
            
            report_lines.extend([
                f"---",
                f"",
                f"**Fin del Reporte Consolidado de Métricas**",
                f"",
                f"*Generado automáticamente por el sistema de investigación Deep Research*",
            ])
            
            # Escribir archivo
            consolidated_report = "\n".join(report_lines)
            
            with open(metrics_file_path, 'w', encoding='utf-8') as f:
                f.write(consolidated_report)
            
            logger.log_success(f"✅ Reporte consolidado de métricas guardado en: {metrics_file_path}")
            print(f"   📊 Total de reportes incluidos: {total_reports}")
            print(f"   💰 Costo total: ${total_cost:.6f}")
            print(f"   📈 Tokens totales: {total_tokens:,}")
            
            return total_cost
            
        except Exception as e:
            logger.log_error(f"⚠️ Error generando reporte consolidado de métricas: {e}")
            import traceback
            traceback.print_exc()
            return 0.0

    def _prepare_initial_state(self, record: Dict[str, Any]) -> ResearchState:
        """Prepara el estado inicial para el grafo basado en el registro de Airtable."""
        fields = record.get('fields', {})
        record_id = record['id']
        
        # Tema/Índice
        topic = fields.get('Topic', fields.get('Tema', fields.get('Title', 'Sin tema')))

        # Brief/Objetivo del capítulo (opcional)
        brief = fields.get('Brief', '')

        # System Prompt y Descripción del Agente
        system_prompt, agent_description = self._get_system_prompt_and_description(fields)
        
        # Si no hay System Prompt, usar uno por defecto
        if not system_prompt:
            system_prompt = "Eres un analista de investigación experto. Genera un informe detallado y preciso."
        
        # Tipo de prompt (buscar en System_Prompt_ID o en campos directos)
        prompt_type = fields.get('Type', fields.get('Category', 'General'))
        if not prompt_type:
            # Intentar obtener desde System_Prompt_ID si está disponible
            prompt_id = fields.get('System_Prompt_ID')
            if prompt_id and isinstance(prompt_id, list):
                prompt_id = prompt_id[0]
            if prompt_id:
                try:
                    from .config import airtable_base, TOML_CONFIG
                    prompts_table_name = TOML_CONFIG.get("airtable", {}).get("prompts_table_name", "System_Prompts")
                    prompts_table = airtable_base.table(prompts_table_name)
                    prompt_record = prompts_table.get(prompt_id)
                    if prompt_record and "fields" in prompt_record:
                        prompt_type = prompt_record["fields"].get("Type") or prompt_record["fields"].get("Category", "General")
                except:
                    pass
        
        # Proyecto relacionado
        # Buscar en múltiples variantes de nombres de campo para compatibilidad
        # En Airtable, las relaciones pueden venir en varios formatos
        project_id = (
            fields.get('Proyecto_ID') or 
            fields.get('Proyecto') or 
            fields.get('Proyectos_NEW') or 
            fields.get('Projectos_NEW') or 
            fields.get('Project') or
            fields.get('proyecto_id') or
            fields.get('proyecto') or
            fields.get('project_id') or
            fields.get('project') or
            # Buscar campos que contengan "proyecto" o "project" en el nombre
            next((fields.get(k) for k in fields.keys() if 'proyecto' in k.lower() or 'project' in k.lower()), None)
        )
        
        # Si project_id es una lista, tomar el primer elemento
        if isinstance(project_id, list) and len(project_id) > 0:
            project_id = project_id[0]
        elif isinstance(project_id, list):
            project_id = None
        
        # Logging para diagnóstico
        logger.log_info(f"🔍 [PROYECTO] Buscando proyecto asociado al item {record_id}...")
        logger.log_info(f"   - Campos disponibles: {list(fields.keys())}")
        logger.log_info(f"   - Proyecto_ID: {fields.get('Proyecto_ID')}")
        logger.log_info(f"   - Proyecto: {fields.get('Proyecto')}")
        logger.log_info(f"   - Proyectos_NEW: {fields.get('Proyectos_NEW')}")
        logger.log_info(f"   - Projectos_NEW: {fields.get('Projectos_NEW')}")
        logger.log_info(f"   - Project: {fields.get('Project')}")
        # Buscar cualquier campo que contenga "proyecto" o "project"
        project_related_fields = [k for k in fields.keys() if 'proyecto' in k.lower() or 'project' in k.lower()]
        if project_related_fields:
            logger.log_info(f"   - Campos relacionados con proyecto encontrados: {project_related_fields}")
            for field_name in project_related_fields:
                logger.log_info(f"      - {field_name}: {fields.get(field_name)}")
        logger.log_info(f"   - project_id final: {project_id}")
        
        if not project_id:
            logger.log_warning(f"   ⚠️ NO se encontró proyecto asociado al item {record_id}")
            logger.log_warning(f"   💡 El item necesita tener un campo que relacione con la tabla Proyectos")
            logger.log_warning(f"   💡 Campos esperados: 'Proyecto_ID', 'Proyecto', 'Proyectos_NEW', 'Project', etc.")
            logger.log_warning(f"   💡 Verificar en Airtable que el item tenga una relación con un proyecto")
        
        project_name = None
        project_specific_context = None
        related_topics = []
        full_index = []
        company_context = {}
        
        if project_id:
            if isinstance(project_id, list):
                project_id = project_id[0]
            try:
                project_record = self.proyectos_table.get(project_id)
                if project_record and "fields" in project_record:
                    pfields = project_record["fields"]
                    # Buscar nombre del proyecto en múltiples variantes de campos
                    # El usuario confirma que el campo se llama "Project_Name" (con guion bajo) en la tabla Proyectos
                    project_name = (
                        pfields.get("Project_Name") or  # Prioridad: campo confirmado por el usuario (con guion bajo)
                        pfields.get("Project Name") or
                        pfields.get("project_name") or
                        pfields.get("Nombre") or 
                        pfields.get("Name") or 
                        pfields.get("Title") or
                        pfields.get("nombre") or
                        pfields.get("name") or
                        pfields.get("title")
                    )
                    
                    # Logging para diagnóstico
                    logger.log_info(f"🔍 [PROYECTO] Campos disponibles en proyecto {project_id}: {list(pfields.keys())}")
                    logger.log_info(f"   - Project_Name encontrado: {project_name}")
                    if not project_name:
                        logger.log_warning(f"   ⚠️ No se encontró Project_Name. Campos disponibles: {list(pfields.keys())}")
                    
                    # Cargar contexto específico del proyecto
                    from .doc_parser import get_project_context
                    from .config import CONTEXT_SOURCE
                    
                    # Intentar múltiples nombres de campo para compatibilidad
                    context_attachments_raw = (
                        pfields.get("Context") or 
                        pfields.get("context") or 
                        pfields.get("Contexto") or 
                        pfields.get("contexto") or 
                        None
                    )
                    
                    # Normalizar el formato de attachments
                    context_attachments = []
                    if context_attachments_raw:
                        if isinstance(context_attachments_raw, list):
                            context_attachments = context_attachments_raw
                        elif isinstance(context_attachments_raw, dict):
                            # Si es un solo dict, convertirlo a lista
                            context_attachments = [context_attachments_raw]
                        elif isinstance(context_attachments_raw, str):
                            # Si es string, intentar parsearlo como JSON
                            try:
                                import json
                                parsed = json.loads(context_attachments_raw)
                                if isinstance(parsed, list):
                                    context_attachments = parsed
                                elif isinstance(parsed, dict):
                                    context_attachments = [parsed]
                            except:
                                logger.log_warning(f"   ⚠️ Campo Context es string pero no es JSON válido: {context_attachments_raw[:100]}")
                        else:
                            logger.log_warning(f"   ⚠️ Campo Context tiene tipo inesperado: {type(context_attachments_raw).__name__}")
                    
                    # Logging detallado para depuración
                    logger.log_info(f"🔍 [CONTEXTO] Modo configurado: {CONTEXT_SOURCE}")
                    logger.log_info(f"🔍 [CONTEXTO] Campos disponibles en proyecto: {list(pfields.keys())}")
                    
                    # DEBUG: Verificar cada variante del campo Context
                    logger.log_info(f"🔍 [CONTEXTO] Verificando campo 'Context': {pfields.get('Context') is not None}")
                    logger.log_info(f"🔍 [CONTEXTO] Verificando campo 'context': {pfields.get('context') is not None}")
                    logger.log_info(f"🔍 [CONTEXTO] Verificando campo 'Contexto': {pfields.get('Contexto') is not None}")
                    logger.log_info(f"🔍 [CONTEXTO] Verificando campo 'contexto': {pfields.get('contexto') is not None}")
                    
                    # DEBUG: Verificar tipo de dato si existe
                    for field_name in ['Context', 'context', 'Contexto', 'contexto']:
                        field_value = pfields.get(field_name)
                        if field_value is not None:
                            logger.log_info(f"🔍 [CONTEXTO] Campo '{field_name}' encontrado: tipo={type(field_value).__name__}, valor={str(field_value)[:100]}")
                    
                    if context_attachments:
                        logger.log_info(f"📄 Campo Context encontrado con {len(context_attachments)} adjunto(s)")
                        # Logging del primer adjunto para diagnóstico
                        if len(context_attachments) > 0:
                            first_att = context_attachments[0]
                            filename = first_att.get('filename', 'N/A') if isinstance(first_att, dict) else 'N/A'
                            logger.log_info(f"   📎 Primer adjunto: {filename} (url: {first_att.get('url', 'N/A')[:50] if isinstance(first_att, dict) else 'N/A'}...)")
                            logger.log_info(f"   📎 Tipo de adjunto: {type(first_att).__name__}, Keys: {list(first_att.keys()) if isinstance(first_att, dict) else 'N/A'}")
                            # Detectar si es Word/DOCX (contiene competidores y planes)
                            if isinstance(first_att, dict) and filename.lower().endswith(('.docx', '.doc')):
                                logger.log_info(f"   ✅ Archivo Word detectado (contiene competidores y planes según el usuario)")
                    else:
                        logger.log_warning(f"⚠️ Campo Context vacío o no encontrado en proyecto {project_id}")
                        # Buscar cualquier campo que pueda contener attachments
                        attachment_fields = [k for k in pfields.keys() if 'context' in k.lower() or 'attach' in k.lower() or 'doc' in k.lower()]
                        if attachment_fields:
                            logger.log_info(f"   💡 Campos relacionados encontrados: {attachment_fields}")
                            # DEBUG: Mostrar el contenido de estos campos
                            for field_name in attachment_fields:
                                field_value = pfields.get(field_name)
                                if field_value:
                                    logger.log_info(f"   💡 Campo '{field_name}': tipo={type(field_value).__name__}, len={len(field_value) if isinstance(field_value, (list, str)) else 'N/A'}")
                    
                    # DEBUG: Logging antes de cargar contexto
                    logger.log_info(f"🔍 [CONTEXTO] Llamando a get_project_context(project_id={project_id})...")
                    
                    project_specific_context = get_project_context(
                        project_id=project_id,
                        attachments=context_attachments
                    )
                    
                    # Logging del resultado con resumen claro
                    logger.log_info("=" * 80)
                    logger.log_info("📋 RESUMEN DE CARGA DE CONTEXTO")
                    logger.log_info("=" * 80)
                    logger.log_info(f"   Modo configurado: {CONTEXT_SOURCE}")
                    logger.log_info(f"   Proyecto ID: {project_id}")
                    logger.log_info(f"   Nombre del proyecto: {project_name}")
                    logger.log_info(f"   Adjuntos encontrados: {len(context_attachments)}")
                    
                    if project_specific_context and project_specific_context.strip():
                        logger.log_success(f"✅ Contexto del proyecto cargado: {len(project_specific_context)} caracteres")
                        # Mostrar preview del contexto (primeros 200 caracteres)
                        preview = project_specific_context[:200].replace('\n', ' ')
                        logger.log_info(f"   📄 Preview: {preview}...")
                        
                        # Verificar contenido clave
                        context_lower = project_specific_context.lower()
                        keywords_found = []
                        if 'acs' in context_lower:
                            keywords_found.append("ACS")
                        if 'competidor' in context_lower or 'competitor' in context_lower:
                            keywords_found.append("competidores")
                        if 'sector' in context_lower or 'industry' in context_lower:
                            keywords_found.append("sector")
                        if keywords_found:
                            logger.log_info(f"   🔍 Palabras clave encontradas: {', '.join(keywords_found)}")
                    else:
                        logger.log_warning(f"⚠️ Contexto del proyecto vacío o no se pudo cargar")
                        if CONTEXT_SOURCE == "airtable" and not context_attachments:
                            logger.log_warning(f"   💡 Sugerencia: Verificar que el campo 'Context' en Airtable contenga adjuntos")
                            logger.log_warning(f"   💡 El campo debe llamarse 'Context' (o 'Contexto') y debe ser de tipo 'Attachment'")
                        elif CONTEXT_SOURCE == "airtable" and context_attachments:
                            logger.log_warning(f"   💡 Adjuntos encontrados pero el procesamiento falló. Verificar logs de Docling.")
                        elif CONTEXT_SOURCE == "local":
                            logger.log_warning(f"   💡 Sugerencia: Verificar que existan archivos .txt/.md en la carpeta de contexto")
                    logger.log_info("=" * 80)
                    
                    # VALIDACIÓN CRÍTICA: NO continuar si no hay contexto
                    if CONTEXT_SOURCE == "airtable":
                        if not project_specific_context or not project_specific_context.strip():
                            logger.log_error("=" * 80)
                            logger.log_error("❌ ERROR CRÍTICO: CONTEXTO NO DISPONIBLE")
                            logger.log_error("=" * 80)
                            logger.log_error("   El contexto del proyecto NO se pudo cargar desde Airtable.")
                            logger.log_error("   ⚠️  EL PROCESAMIENTO SE DETIENE - El contexto es OBLIGATORIO")
                            logger.log_error("")
                            logger.log_error("   Para solucionarlo:")
                            logger.log_error("   1. Verifica que el campo 'Context' existe en la tabla Proyectos")
                            logger.log_error("   2. Verifica que el campo 'Context' contiene adjuntos")
                            logger.log_error("   3. Verifica que los adjuntos son archivos válidos (PDF, DOCX, TXT, etc.)")
                            logger.log_error("   4. Verifica que Docling puede procesar los archivos")
                            logger.log_error("=" * 80)
                            raise ValueError(f"CONTEXTO OBLIGATORIO NO DISPONIBLE: El proyecto {project_id} no tiene contexto cargado desde Airtable. El procesamiento se detiene.")
                        else:
                            logger.log_success("✅ CONTEXTO DISPONIBLE: El procesamiento continuará con contexto completo")
                    elif CONTEXT_SOURCE == "local":
                        if not project_specific_context or not project_specific_context.strip():
                            logger.log_error("=" * 80)
                            logger.log_error("❌ ERROR CRÍTICO: CONTEXTO NO DISPONIBLE")
                            logger.log_error("=" * 80)
                            logger.log_error("   El contexto del proyecto NO se pudo cargar desde carpeta local.")
                            logger.log_error("   ⚠️  EL PROCESAMIENTO SE DETIENE - El contexto es OBLIGATORIO")
                            logger.log_error("")
                            logger.log_error("   Para solucionarlo:")
                            logger.log_error("   1. Verifica que la carpeta de contexto existe")
                            logger.log_error("   2. Verifica que contiene archivos .txt o .md")
                            logger.log_error("=" * 80)
                            raise ValueError(f"CONTEXTO OBLIGATORIO NO DISPONIBLE: No se encontró contexto en la carpeta local. El procesamiento se detiene.")
                        else:
                            logger.log_success("✅ CONTEXTO DISPONIBLE: El procesamiento continuará con contexto completo")
                    
                    # Obtener índice completo desde los items del proyecto (ya no existe get_project_index)
                    # El full_index se obtiene más abajo junto con related_topics
                    full_index = []
                    
                    # Obtener índice completo y temas relacionados (todos los items del mismo proyecto)
                    try:
                        logger.log_info(f"🔍 [ITEMS RELACIONADOS] Buscando items del proyecto {project_id}...")
                        
                        # Estrategia 1: Buscar usando link fields (campos de relación en Airtable)
                        # Para link fields en Airtable, podemos buscar directamente usando el ID del registro
                        field_variants = [
                            "Proyectos_NEW",  # Campo de relación más común
                            "Projectos_NEW",  # Variante con typo
                            "Proyecto",       # Campo de relación simple
                            "Project",        # Campo en inglés
                            "Proyecto_ID",    # Campo de ID (si es texto)
                            "Project_ID",     # Campo de ID en inglés
                            "proyecto_id",    # Variante lowercase
                            "project_id",     # Variante lowercase inglés
                        ]
                        related_items = []
                        
                        # Estrategia 1a: Buscar usando fórmula directa con link fields
                        # En Airtable, para link fields puedes buscar usando el ID directamente
                        for field_name in field_variants[:4]:  # Solo los primeros 4 son link fields probables
                            try:
                                # Intentar búsqueda directa (funciona para link fields en algunos casos)
                                items_formula = f"{{{field_name}}}='{project_id}'"
                                related_items = self.items_table.all(formula=items_formula)
                                if related_items:
                                    logger.log_info(f"   ✅ Encontrados {len(related_items)} items usando link field '{field_name}' (fórmula directa)")
                                    break
                            except Exception as e:
                                # Si falla, continuar con siguiente variante
                                continue
                        
                        # Estrategia 1b: Si no funcionó, intentar con campos de texto/ID
                        if not related_items:
                            for field_name in field_variants[4:]:  # Campos de ID/texto
                                try:
                                    items_formula = f"{{{field_name}}}='{project_id}'"
                                    related_items = self.items_table.all(formula=items_formula)
                                    if related_items:
                                        logger.log_info(f"   ✅ Encontrados {len(related_items)} items usando campo '{field_name}'")
                                        break
                                except Exception as e:
                                    continue
                        
                        # Estrategia 2: Buscar todos los items y filtrar manualmente (fallback más robusto)
                        if not related_items:
                            try:
                                logger.log_info(f"   🔍 Intentando búsqueda manual de items relacionados...")
                                # Obtener una muestra de items para verificar estructura
                                sample_items = self.items_table.all(max_records=10)
                                if sample_items:
                                    # Verificar qué campos tienen los items
                                    sample_fields = set()
                                    for item in sample_items:
                                        sample_fields.update(item.get('fields', {}).keys())
                                    logger.log_info(f"   📋 Campos disponibles en items: {sorted(sample_fields)}")
                                
                                # Buscar todos los items (con límite razonable)
                                all_items = self.items_table.all(max_records=500)  # Aumentado a 500 para proyectos grandes
                                logger.log_info(f"   🔍 Analizando {len(all_items)} items para encontrar relaciones...")
                                
                                for item in all_items:
                                    item_fields = item.get('fields', {})
                                    # Verificar cada variante de campo
                                    for field_name in field_variants:
                                        field_value = item_fields.get(field_name)
                                        if field_value:
                                            # Si es lista (link field), verificar si contiene el project_id
                                            if isinstance(field_value, list):
                                                # Verificar si el project_id está en la lista (puede ser string o dict con 'id')
                                                for x in field_value:
                                                    if isinstance(x, dict) and x.get('id') == project_id:
                                                        related_items.append(item)
                                                        break
                                                    elif isinstance(x, str) and x == project_id:
                                                        related_items.append(item)
                                                        break
                                                if item in related_items:
                                                    break
                                            # Si es string, comparar directamente
                                            elif isinstance(field_value, str) and field_value == project_id:
                                                related_items.append(item)
                                                break
                                
                                if related_items:
                                    logger.log_info(f"   ✅ Encontrados {len(related_items)} items usando búsqueda manual")
                                else:
                                    logger.log_warning(f"   ⚠️ No se encontraron items relacionados después de analizar {len(all_items)} items")
                                    logger.log_info(f"   💡 Verifica en Airtable que los items tengan un campo de relación con el proyecto")
                                    logger.log_info(f"   💡 Campos probados: {', '.join(field_variants)}")
                            except Exception as e:
                                logger.log_warning(f"   ⚠️ Error en búsqueda manual: {e}")
                                import traceback
                                logger.log_warning(f"   📋 Traceback: {traceback.format_exc()}")
                        
                        if related_items:
                            # full_index: todos los topics del proyecto (incluyendo el actual)
                            full_index = [
                                item.get('fields', {}).get('Topic') or 
                                item.get('fields', {}).get('Tema') or 
                                item.get('fields', {}).get('Title', '')
                                for item in related_items
                                if item.get('fields', {}).get('Topic') or 
                                   item.get('fields', {}).get('Tema') or 
                                   item.get('fields', {}).get('Title')
                            ]
                            
                            # related_topics: otros temas del proyecto (excluyendo el actual)
                            related_topics = [
                                item.get('fields', {}).get('Topic') or 
                                item.get('fields', {}).get('Tema') or 
                                item.get('fields', {}).get('Title', '')
                                for item in related_items
                                if item.get('id') != record_id and (
                                    item.get('fields', {}).get('Topic') or 
                                    item.get('fields', {}).get('Tema') or 
                                    item.get('fields', {}).get('Title')
                                )
                            ]
                            
                            logger.log_info(f"   📚 Índice completo del proyecto: {len(full_index)} items")
                            logger.log_info(f"   📋 Temas relacionados: {len(related_topics)} items")
                        else:
                            logger.log_warning(f"   ⚠️ No se encontraron items relacionados para el proyecto {project_id}")
                            logger.log_info(f"   💡 Verifica en Airtable que los items tengan un campo de relación con el proyecto")
                            logger.log_info(f"   💡 Campos probados: {', '.join(field_variants)}")
                            full_index = []
                            related_topics = []
                    except Exception as e:
                        logger.log_warning(f"   ⚠️ Error obteniendo información del proyecto {project_id}: {e}")
                        import traceback
                        logger.log_warning(f"   📋 Traceback: {traceback.format_exc()}")
                        full_index = []
                        related_topics = []
                    
                    # Cargar contexto de empresa (si existe)
                    company_context_field = pfields.get("Company_Context") or pfields.get("Context")
                    if company_context_field:
                        # Si es texto, usarlo directamente
                        if isinstance(company_context_field, str):
                            company_context = {"general": company_context_field}
                        # Si es un diccionario/objeto, usarlo tal cual
                        elif isinstance(company_context_field, dict):
                            company_context = company_context_field
            except Exception as e:
                logger.log_warning(f"Error obteniendo información del proyecto {project_id}: {e}")
        
        # Fuentes existentes - NO cargar cuando se reprocesa (status era "Todo")
        # Esto evita acumulación infinita de fuentes de ejecuciones anteriores
        # Las fuentes nuevas serán las únicas usadas para el reporte
        existing_sources_text = ""  # Limpiar para empezar fresco cada ejecución
        
        # Estado inicial
        # Validar que project_specific_context sea string o None (nunca False)
        if project_specific_context is False:
            logger.log_warning("⚠️ project_specific_context es False, normalizando a None")
            project_specific_context = None
        
        # Logging final antes de crear el estado
        logger.log_info("=" * 80)
        logger.log_info("📋 VERIFICACIÓN FINAL DEL CONTEXTO EN ESTADO INICIAL")
        logger.log_info("=" * 80)
        logger.log_info(f"   - project_id: {project_id}")
        logger.log_info(f"   - project_name: {project_name}")
        logger.log_info(f"   - project_specific_context tipo: {type(project_specific_context).__name__}")
        logger.log_info(f"   - project_specific_context valor: {project_specific_context if project_specific_context is None else 'string con contenido'}")
        if project_specific_context and isinstance(project_specific_context, str):
            logger.log_info(f"   - project_specific_context longitud: {len(project_specific_context)} caracteres")
            logger.log_info(f"   - project_specific_context preview: {project_specific_context[:100]}...")
        logger.log_info("=" * 80)
        
        initial_state: ResearchState = {
            "topic": topic,
            "search_strategy": [],
            "found_sources": [],
            "validated_sources": [],
            "rejected_sources": [],
            "final_report": "",
            "updated_sources_text": existing_sources_text,
            "existing_sources_text": existing_sources_text,
            "system_prompt": system_prompt,
            "agent_description": agent_description,
            "brief": brief,
            "prompt_type": prompt_type,
            "report_type": prompt_type,  # Capa C y D: report_type = prompt_type para lógica condicional
            "project_id": project_id,  # Añadir project_id al estado para ContextManager
            "project_name": project_name,
            "project_specific_context": project_specific_context if project_specific_context else None,  # Asegurar que sea string o None
            "related_topics": related_topics,
            "full_index": full_index,
            "company_context": company_context,
            "loop_count": 0,
            "failed_queries": [],
            "quality_gate_passed": False,
            "quality_gate_issues": [],
            "quality_gate_recommendation": "PROCEED",
            "confidence_score": {},
            "tokens_by_role": {},
            "plot_data": [],
            "verification_issues": [],
            "verification_passed": True,
            "logs": []
        }
        
        return initial_state

    async def run_loop(self, run_once: bool = False):
        """Bucle principal de procesamiento."""
        # Crear el semáforo dentro del loop de eventos actual
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        mode_text = "Ejecución única" if run_once else "Bucle continuo"
        logger.log_section("Iniciando Manager Asíncrono", f"Modo: {mode_text}")
        
        consecutive_empty = 0
        
        while self.running:
            # 1. Buscar tareas
            try:
                # Ejecutar búsqueda en thread para no bloquear (Ahora busca 'Pending')
                loop = asyncio.get_running_loop()
                records = await loop.run_in_executor(None, lambda: self.items_table.all(formula="{Status}='Pending'"))
            except Exception as e:
                logger.log_warning(f"Error conectando con Airtable: {e}")
                if run_once:
                     break
                await asyncio.sleep(10)
                continue
                
            if not records:
                if run_once:
                    logger.log_info("No hay items con Status='Pending'. Terminando.")
                    break

                consecutive_empty += 1
                if consecutive_empty % 6 == 0:
                    print(".", end="", flush=True) # Minimal feedback for waiting
                await asyncio.sleep(5)
                continue
                
            consecutive_empty = 0
            logger.log_info(f"Encontradas {len(records)} tareas pendientes.")
            
            # 2. Lanzar procesamiento concurrente
            tasks = [self.process_item(record) for record in records]
            
            # await asyncio.gather(*tasks) # Esto espera a que TODAS terminen antes de buscar más
            # Para un flujo más continuo, podríamos lanzarlas y seguir, pero por simplicidad
            # procesamos el lote encontrado y luego buscamos más.
            await asyncio.gather(*tasks)
            
            if run_once:
                logger.log_success("Ejecución única completada.")
                # Generar reporte consolidado de métricas al final
                total_cost = self._generate_consolidated_metrics_report()
                return total_cost if total_cost is not None else 0.0
        
        # Si salimos del loop sin items, también generamos el reporte si hay métricas
        if self._metrics_accumulator:
            total_cost = self._generate_consolidated_metrics_report()
            return total_cost if total_cost is not None else 0.0
        
        return 0.0

def run_async_processor(run_once: bool = False):
    """Ejecuta el procesador asíncrono.
    
    Args:
        run_once: Si es True, procesa solo una vez y termina
        
    Returns:
        float: Costo total de la ejecución en dólares
    """
    manager = ResearchManager(concurrency_limit=CONCURRENCY_LIMIT)
    try:
        total_cost = asyncio.run(manager.run_loop(run_once=run_once))
        return total_cost if total_cost is not None else 0.0
    except KeyboardInterrupt:
        logger.log_info("Deteniendo manager...")
        return 0.0