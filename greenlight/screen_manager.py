from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Any, Dict

class NavigationAction(Enum):
    PUSH = "push"
    POP = "pop"
    REPLACE = "replace"
    EXIT = "exit"

class ScreenResult:
    def __init__(self, action: NavigationAction, screen_class=None, context=None):
        self.action = action
        self.screen_class = screen_class
        self.context = context

class Screen(ABC):
    def __init__(self, ui_base, context=None):
        self.ui = ui_base
        self.context = context or {}
    
    def enter(self):
        """Called when screen becomes active"""
        pass
    
    @abstractmethod
    def run(self) -> ScreenResult:
        """Execute screen logic, return navigation action"""
        pass
    
    def exit(self):
        """Called when leaving screen"""
        pass

class ScreenManager:
    def __init__(self, ui_base):
        self.ui = ui_base
        self.screen_stack = []
        self.running = True
    
    def push_screen(self, screen_class, context=None):
        """Add screen to stack"""
        screen = screen_class(self.ui, context)
        screen.enter()
        self.screen_stack.append(screen)
    
    def pop_screen(self):
        """Remove current screen, return to previous"""
        if len(self.screen_stack) > 1:
            current_screen = self.screen_stack.pop()
            current_screen.exit()
    
    def replace_screen(self, screen_class, context=None):
        """Replace current screen"""
        if self.screen_stack:
            current_screen = self.screen_stack.pop()
            current_screen.exit()
        self.push_screen(screen_class, context)
    
    def handle_action(self, result: ScreenResult):
        """Process navigation action"""
        if result.action == NavigationAction.PUSH:
            self.push_screen(result.screen_class, result.context)
        elif result.action == NavigationAction.POP:
            self.pop_screen()
        elif result.action == NavigationAction.REPLACE:
            self.replace_screen(result.screen_class, result.context)
        elif result.action == NavigationAction.EXIT:
            self.running = False
    
    def run(self):
        """Main application loop"""
        while self.running and self.screen_stack:
            current_screen = self.screen_stack[-1]
            result = current_screen.run()
            self.handle_action(result)
        
        # Clean up remaining screens
        while self.screen_stack:
            screen = self.screen_stack.pop()
            screen.exit()