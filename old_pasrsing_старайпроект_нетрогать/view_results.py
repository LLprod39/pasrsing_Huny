#!/usr/bin/env python3
"""
Скрипт для просмотра результатов парсинга
"""
import json
import sys

def main():
    filename = 'synergy_full_data_20251006_231713.json'
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print("=== РЕЗУЛЬТАТЫ ПАРСИНГА ===")
        print(f"Семестров: {data['total_semesters']}")
        print(f"Курсов: {data['total_courses']}")
        print(f"Материалов: {data['total_materials']}")
        print(f"Дата парсинга: {data['parsed_at']}")
        
        print("\n=== СЕМЕСТРЫ ===")
        for semester in data['semesters']:
            print(f"Семестр {semester['number']}: {len(semester['courses'])} курсов")
        
        print("\n=== ПРИМЕРЫ МАТЕРИАЛОВ ===")
        if data['semesters'] and data['semesters'][0]['courses']:
            course = data['semesters'][0]['courses'][0]
            print(f"Курс: {course['name']}")
            print(f"Материалов в курсе: {len(course['materials'])}")
            
            print("\nПервые 5 материалов:")
            for i, mat in enumerate(course['materials'][:5]):
                print(f"{i+1}. {mat['name']}")
                print(f"   Тип: {mat['type']}")
                print(f"   Заблокирован: {mat['is_blocked']}")
                print(f"   Прогресс: {mat['progress']}")
                print(f"   Статус: {mat['completion_status']}")
                print()
        
        print("\n=== СТАТИСТИКА ПО ТИПАМ МАТЕРИАЛОВ ===")
        type_counts = {}
        blocked_count = 0
        
        for semester in data['semesters']:
            for course in semester['courses']:
                for material in course['materials']:
                    mat_type = material['type']
                    type_counts[mat_type] = type_counts.get(mat_type, 0) + 1
                    if material['is_blocked']:
                        blocked_count += 1
        
        for mat_type, count in sorted(type_counts.items()):
            print(f"{mat_type}: {count}")
        
        print(f"\nЗаблокированных материалов: {blocked_count}")
        
    except FileNotFoundError:
        print(f"Файл {filename} не найден!")
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    main()

