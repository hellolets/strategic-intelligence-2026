#!/usr/bin/env python3
"""
Script para detectar truncamiento en respuestas del Judge.
Busca en logs y analiza respuestas JSON incompletas.
"""

import json
import re
import os
from pathlib import Path
from typing import List, Dict, Tuple

def detect_truncated_json(content: str) -> Tuple[bool, str]:
    """
    Detecta si un JSON está truncado.
    
    Returns:
        (is_truncated, reason)
    """
    content = content.strip()
    
    # Verificar si es JSON válido
    try:
        json.loads(content)
        return False, "JSON válido"
    except json.JSONDecodeError as e:
        # Verificar si falta cierre
        open_braces = content.count('{')
        close_braces = content.count('}')
        
        if open_braces > close_braces:
            return True, f"JSON incompleto: faltan {open_braces - close_braces} llaves de cierre"
        
        # Verificar si termina abruptamente
        if not content.endswith('}'):
            # Verificar si el último carácter es parte de un string
            if not content.endswith('"') and '"' in content:
                return True, "JSON cortado a mitad de string"
            return True, "JSON no termina correctamente"
        
        return True, f"Error de parsing: {str(e)}"

def check_logs_for_truncation(log_dir: str = "logs") -> List[Dict]:
    """
    Busca errores de truncamiento en logs.
    """
    issues = []
    log_path = Path(log_dir)
    
    if not log_path.exists():
        return [{"type": "error", "message": f"Directorio {log_dir} no existe"}]
    
    # Buscar archivos de log
    log_files = list(log_path.glob("*.log"))
    
    for log_file in sorted(log_files, key=lambda x: x.stat().st_mtime, reverse=True)[:10]:  # Últimos 10
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # Buscar errores de JSON
                json_errors = re.findall(r'Error parseando JSON[^\n]*', content, re.IGNORECASE)
                json_decode_errors = re.findall(r'JSONDecodeError[^\n]*', content, re.IGNORECASE)
                json_content_errors = re.findall(r'Contenido:.*?\.\.\.', content, re.IGNORECASE)
                
                if json_errors or json_decode_errors:
                    issues.append({
                        "file": log_file.name,
                        "type": "json_error",
                        "count": len(json_errors) + len(json_decode_errors),
                        "errors": (json_errors[:3] + json_decode_errors[:3])[:5],  # Primeros 5
                        "content_previews": json_content_errors[:3]
                    })
        except Exception as e:
            issues.append({
                "file": log_file.name,
                "type": "error",
                "message": f"Error leyendo log: {e}"
            })
    
    return issues

def analyze_response_length(content: str, max_tokens: int) -> Dict:
    """
    Analiza si una respuesta excede el límite de tokens.
    """
    # Estimación: 1 token ≈ 4 caracteres
    estimated_tokens = len(content) // 4
    
    return {
        "content_length": len(content),
        "estimated_tokens": estimated_tokens,
        "max_tokens": max_tokens,
        "exceeds_limit": estimated_tokens > max_tokens,
        "usage_percent": (estimated_tokens / max_tokens * 100) if max_tokens > 0 else 0
    }

if __name__ == "__main__":
    print("=" * 100)
    print("🔍 DETECTOR DE TRUNCAMIENTO EN JUDGE")
    print("=" * 100)
    print()
    
    # 1. Buscar en logs
    print("📋 Buscando errores en logs...")
    log_issues = check_logs_for_truncation()
    
    if log_issues:
        total_errors = sum(issue.get("count", 0) for issue in log_issues if issue.get("type") == "json_error")
        print(f"   ⚠️ Encontrados {len(log_issues)} archivos con errores (total: {total_errors} errores):")
        print()
        for issue in log_issues:
            if issue["type"] == "json_error":
                print(f"   📄 {issue['file']}: {issue['count']} errores de JSON")
                for error in issue.get('errors', [])[:2]:
                    print(f"      - {error[:100]}")
                if issue.get('content_previews'):
                    print(f"      Previews de contenido truncado:")
                    for preview in issue['content_previews'][:2]:
                        print(f"         {preview[:120]}")
                print()
    else:
        print("   ✅ No se encontraron errores de JSON en logs recientes")
    
    print()
    print("=" * 100)
    print("📊 INDICADORES DE TRUNCAMIENTO:")
    print("=" * 100)
    print()
    print("1. ❌ Errores de parsing JSON en logs")
    print("2. ⚠️ JSON que no termina con '}'")
    print("3. 📉 Reasoning cortado a mitad de frase")
    print("4. 🔍 Campos faltantes en la respuesta")
    print("5. 📏 Respuestas que exceden el límite de tokens")
    print()
    print("=" * 100)
    print("💡 CÓMO USAR:")
    print("=" * 100)
    print()
    print("1. Ejecutar este script regularmente:")
    print("   python3 detect_truncation.py")
    print()
    print("2. Buscar en logs manualmente:")
    print("   grep -i 'error parseando json' logs/*.log")
    print("   grep -i 'JSONDecodeError' logs/*.log")
    print()
    print("3. Si encuentras errores:")
    print("   - Revisar config.toml: judge_cheap_max_output_tokens")
    print("   - Considerar aumentar de 800 a 1000 tokens")
    print("   - Verificar que judge_premium (1200) se use para casos complejos")
    print()
    print("4. Monitorear durante ejecuciones:")
    print("   - Observar mensajes 'Error parseando JSON'")
    print("   - Verificar 'Contenido: ...' que muestre JSON incompleto")
    print()
