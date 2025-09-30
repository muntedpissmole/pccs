# modules/rules.py
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class RulesEngine:
    def __init__(self, rules_file, phase_manager, reeds_controller, get_computed_dt, action_handlers, on_rule_fired=None):
        self.phase_manager = phase_manager
        self.reeds_controller = reeds_controller
        self.get_computed_dt = get_computed_dt
        self.action_handlers = action_handlers
        self.on_rule_fired = on_rule_fired
        self.last_execution = {}
        self.rules = []
        try:
            with open(rules_file, 'r') as f:
                self.rules = json.load(f)
            logger.info(f"Loaded {len(self.rules)} rules from {rules_file}")
        except Exception as e:
            logger.error(f"Failed to load rules: {e}")

    def evaluate_condition(self, cond, context):
        if not isinstance(cond, dict):
            logger.warning("Invalid condition format")
            return False
        if 'and' in cond:
            return all(self.evaluate_condition(sub, context) for sub in cond['and'])
        elif 'or' in cond:
            return any(self.evaluate_condition(sub, context) for sub in cond['or'])
        else:
            if len(cond) != 1:
                logger.warning("Invalid condition: multiple keys")
                return False
            key, val = next(iter(cond.items()))
            if key == 'phase':
                return self.phase_manager.current_phase == val
            elif key == 'new_phase':
                return context.get('new_phase') == val
            elif key == 'reed_open':
                button = self.reeds_controller.reeds.get(val)
                return button and not button.is_pressed
            elif key == 'reed_id':
                reed_id = context.get('reed_id')
                if isinstance(val, list):
                    return reed_id in val
                else:
                    return reed_id == val
            elif key == 'new_state':
                return context.get('new_state') == val
            elif key == 'event_type':
                return context.get('event_type') == val
            else:
                logger.warning(f"Unknown condition key: {key}")
                return False

    def execute_actions(self, actions):
        for action in actions:
            if not isinstance(action, dict) or len(action) != 1:
                logger.warning("Invalid action format")
                continue
            key, val = next(iter(action.items()))
            if key in self.action_handlers:
                try:
                    self.action_handlers[key](val)
                    logger.debug(f"Executed action {key} with {val}")
                except Exception as e:
                    logger.error(f"Error executing action {key}: {e}")
            else:
                logger.warning(f"Unknown action {key}")

    def on_phase_change(self, new_phase):
        context = {'new_phase': new_phase}
        self._trigger_rules('phase_changed', context)

    def on_reed_state_change(self, reed_id, new_state):
        context = {'reed_id': reed_id, 'new_state': new_state}
        self._trigger_rules('reed_state_changed', context)

    def on_time_event(self, event_type):
        context = {'event_type': event_type}
        self._trigger_rules('time_event', context)

    def _trigger_rules(self, trigger_type, context):
        current_dt = self.get_computed_dt()
        if current_dt is None:
            logger.warning("Cannot trigger rules without current datetime")
            return
        for rule in self.rules:
            if rule.get('trigger') != trigger_type:
                continue
            rule_id = rule.get('id')
            if not rule_id:
                logger.warning("Rule missing id, skipping")
                continue
            if rule.get('once_per_day', False):
                last = self.last_execution.get(rule_id)
                if last and last.date() == current_dt.date():
                    logger.debug(f"Skipping rule {rule_id} (already executed today)")
                    continue
            if 'conditions' in rule and not self.evaluate_condition(rule['conditions'], context):
                continue
            if self.on_rule_fired:
                self.on_rule_fired(rule)
            self.execute_actions(rule.get('actions', []))
            if rule.get('once_per_day', False):
                self.last_execution[rule_id] = current_dt
                logger.debug(f"Updated last execution for {rule_id}")

    def evaluate_on_startup(self):
        current_phase = self.phase_manager.current_phase
        current_dt = self.get_computed_dt()
        if current_dt is None:
            logger.warning("Cannot evaluate rules on startup without current datetime")
            return
        for rule in self.rules:
            if not rule.get('evaluate_on_startup', False):
                continue
            rule_id = rule.get('id')
            if not rule_id:
                continue
            if rule.get('once_per_day', False):
                last = self.last_execution.get(rule_id)
                if last and last.date() == current_dt.date():
                    logger.debug(f"Skipping rule {rule_id} on startup (already executed today)")
                    continue
            trigger = rule.get('trigger')
            satisfied = False
            if trigger == 'phase_changed':
                context = {'new_phase': current_phase}
                if 'conditions' in rule:
                    satisfied = self.evaluate_condition(rule['conditions'], context)
            elif trigger == 'reed_state_changed':
                for reed_id, button in self.reeds_controller.reeds.items():
                    state = "Closed" if button.is_pressed else "Open"
                    context = {'reed_id': reed_id, 'new_state': state}
                    if 'conditions' in rule and self.evaluate_condition(rule['conditions'], context):
                        satisfied = True
                        break
            else:
                logger.debug(f"Skipping unknown trigger {trigger} on startup")
                continue
            if satisfied:
                if self.on_rule_fired:
                    self.on_rule_fired(rule)
                self.execute_actions(rule.get('actions', []))
                if rule.get('once_per_day', False):
                    self.last_execution[rule_id] = current_dt
                    logger.debug(f"Updated last execution for {rule_id} after startup evaluation")