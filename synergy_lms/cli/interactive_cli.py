"""Главный файл для запуска парсера LMS Synergy"""
import sys
from synergy_lms.config import Config
from synergy_lms.logger import setup_logger
from synergy_lms.lms.auth import AuthManager
from synergy_lms.lms.course_parser import CourseParser
from synergy_lms.lms.material_processor import MaterialProcessor
from synergy_lms.lms.test_solver import TestSolver

logger = setup_logger(__name__)


def main():
    """Главная функция"""
    auth_manager = None
    
    try:
        # Валидация конфигурации
        Config.validate()
        logger.info("Конфигурация загружена успешно")
        
        # Создаем менеджер авторизации
        auth_manager = AuthManager()
        
        # Выполняем авторизацию
        logger.info("Начинаем авторизацию...")
        if not auth_manager.login():
            logger.error("Не удалось авторизоваться. Проверьте логин и пароль в .env файле")
            sys.exit(1)
        
        logger.info("Авторизация успешна! Готов к работе.")
        
        # Создаем парсеры
        course_parser = CourseParser(auth_manager.driver)
        material_processor = MaterialProcessor(auth_manager.driver)
        test_solver = TestSolver(auth_manager.driver)
        
        # Главный цикл работы
        while True:
            # Получаем список семестров
            semesters = course_parser.get_available_semesters()
            if not semesters:
                logger.error("Не удалось найти доступные семестры.")
                break
            
            # Выбор семестра
            print("\n" + "=" * 60)
            print(">>> ДОСТУПНЫЕ СЕМЕСТРЫ <<<")
            for sem in semesters:
                print(f"  - Семестр {sem}")
            print("  - введите 'выход' для завершения работы")
            print("=" * 60 + "\n")
            
            try:
                choice = input(">>> Введите номер семестра (или 'выход'): ").strip()
                if choice.lower() in ['выход', 'exit', 'q']:
                    logger.info("Завершение работы...")
                    break
                
                chosen_semester = int(choice)
                if chosen_semester not in semesters:
                    print(f"Ошибка: Семестр {chosen_semester} не найден.")
                    continue
            except ValueError:
                print("Ошибка: Введите корректное число.")
                continue
            except (EOFError, KeyboardInterrupt):
                print("\nОтмена операции. Выход.")
                break
            
            # Получаем курсы семестра
            courses = course_parser.get_semester_courses(chosen_semester)
            if not courses:
                logger.warning(f"В семестре {chosen_semester} не найдено курсов.")
                continue
            
            # Выбор курсов
            print("\n" + "=" * 60)
            print(f">>> КУРСЫ В СЕМЕСТРЕ {chosen_semester} <<<")
            for i, course in enumerate(courses):
                print(f"  {i + 1}. {course['name']} ({course['control_type']})")
            print("  - введите 'назад' для возврата к выбору семестра")
            print("  - введите 'все' для обработки всех курсов")
            print("=" * 60 + "\n")
            
            try:
                choice_str = input(f">>> Введите номера курсов (через запятую, 'все' или 'назад'): ").strip().lower()
                
                if choice_str == 'назад':
                    continue
                
                if choice_str == 'все':
                    courses_to_process = courses
                else:
                    choices = [int(c.strip()) for c in choice_str.split(',')]
                    courses_to_process = [courses[c - 1] for c in choices if 1 <= c <= len(courses)]
                    
                    if not courses_to_process:
                        print("Ошибка: Некорректные номера курсов.")
                        continue
            except (ValueError, EOFError, KeyboardInterrupt):
                print("\nНеверный ввод или отмена.")
                continue
            
            # Обработка выбранных курсов
            for course in courses_to_process:
                logger.info(f"\n{'='*20} Начинаем обработку курса: {course['name']} {'='*20}")
                
                try:
                    # Получаем материалы курса
                    structured_materials = course_parser.get_course_materials(course['url'])
                    flat_materials = course_parser.flatten_materials(structured_materials)
                    
                    # Добавляем course_url к каждому материалу для правильного открытия видео
                    for material in flat_materials:
                        material['course_url'] = course['url']
                    
                    if not flat_materials:
                        logger.warning(f"В курсе '{course['name']}' нет доступных материалов для обработки.")
                        continue
                    
                    # Выбор материалов
                    print("\n" + "=" * 60)
                    print(f">>> МАТЕРИАЛЫ КУРСА: {course['name']} <<<")
                    for i, material in enumerate(flat_materials):
                        material_type_icon = "📹" if material.get('type') == 'video' else "📝" if material.get('type') == 'test' else "📄"
                        print(f"  {i + 1}. {material_type_icon} {material['name']}")
                    print("  - введите 'все' для обработки всех материалов")
                    print("  - введите 'назад' для возврата к выбору курса")
                    print("=" * 60 + "\n")
                    
                    try:
                        choice_str = input(f">>> Введите номера материалов (через запятую, 'все' или 'назад'): ").strip().lower()
                        
                        if choice_str == 'назад':
                            break
                        
                        if choice_str == 'все':
                            materials_to_process = flat_materials
                        else:
                            choices = [int(c.strip()) for c in choice_str.split(',')]
                            materials_to_process = [flat_materials[c - 1] for c in choices if 1 <= c <= len(flat_materials)]
                            
                            if not materials_to_process:
                                print("Ошибка: Некорректные номера материалов.")
                                continue
                    except (ValueError, EOFError, KeyboardInterrupt):
                        print("\nНеверный ввод или отмена.")
                        continue
                    
                    # Обработка материалов
                    processed_count = 0
                    test_count = 0
                    video_count = 0
                    
                    for material in materials_to_process:
                        material_type = material.get('type', 'material')
                        
                        if material_type == 'test':
                            logger.info(f"Проходим тест: {material['name']}")
                            result = test_solver.solve_test(material['url'], material['name'], course_url=material.get('course_url'))
                            if result.get('solved'):
                                test_count += 1
                                processed_count += 1
                                logger.info(f"✅ Тест '{material['name']}' пройден. Оценка: {result.get('score', 'N/A')}")
                            else:
                                logger.error(f"❌ Ошибка при прохождении теста '{material['name']}': {result.get('error')}")
                        else:
                            logger.info(f"Обрабатываем материал: {material['name']}")
                            result = material_processor.process_material(material)
                            if result.get('processed'):
                                processed_count += 1
                                if result.get('videos'):
                                    video_count += 1
                                logger.info(f"✅ Материал '{material['name']}' обработан")
                            else:
                                logger.error(f"❌ Ошибка при обработке материала '{material['name']}': {result.get('error')}")
                    
                    logger.info(f"\n{'='*20} Итоги обработки курса '{course['name']}' {'='*20}")
                    logger.info(f"Обработано материалов: {processed_count}/{len(materials_to_process)}")
                    logger.info(f"  - Видео: {video_count}")
                    logger.info(f"  - Тесты: {test_count}")
                    
                except Exception as e:
                    logger.error(f"Ошибка при обработке курса {course['name']}: {e}", exc_info=True)
                    continue
            
    except KeyboardInterrupt:
        logger.info("Работа прервана пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if auth_manager:
            auth_manager.close()


if __name__ == "__main__":
    main()
