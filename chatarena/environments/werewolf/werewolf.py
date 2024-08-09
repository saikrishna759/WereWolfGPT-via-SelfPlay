import random
from typing import Dict, List, Union
import sys
import json
from ...agent import SIGNAL_END_OF_CONVERSATION
from ...message import Message, MessagePool
from ..base import Environment, TimeStep, register_env
from itertools import islice
DAY_DISSCUSION = 0
DAY_VOTE = 1
NIGHT_DISSCUSION = 2
NIGHT_VOTE = 3
REVEAL = 4
DEFAULT_PLAYER_COUNT = 7
WEREWOLF = 0
TOWNSFOLK = 1
GUARD = 2
SEER = 3
WITCH = 4
HUNTER = 5
DEAD = 0
ALIVE = 1
#2 Werewolfs and 5 Townsfolk
DEFAULT_DISTRIBUTION = [2, 5, 0, 0, 0, 0]
DEFAULT_PROMPTS = "prompt_jsons/default.json"
DEFAULT_DISCUSSION_ROUNDS = 2
@register_env
class Werewolf(Environment):
    type_name = "werewolf"
    def __init__(
        self,
        player_names: List[str],
        **kwargs,
    ):
        super().__init__(player_names=player_names, **kwargs)
        self.message_pool = MessagePool()
        # Game states
        #Turn Counters
        self._current_turn = 0
        self._next_player_idx = 0
        self._discussion_count = 0
        self._discussion_max = DEFAULT_DISCUSSION_ROUNDS * len(player_names)
        self._current_phase = DAY_DISSCUSION
        #Player votes and states
        self.players_votes = None
        self.player_status = None
        self.werewolf_list = None
        self.night_vote_dict = {}
        self.day_vote_dict = {}
        #prompts
        self.prompt_dict = None
        self._initialized = False
        self.reset()

    def get_next_player(self) -> str:
        """Get the next player."""
        if self.is_terminal():
            return None
        while self.player_status[self._next_player_idx] != ALIVE:
            self._next_player_idx = (self._next_player_idx + 1) % len(self.player_names)
        return self.player_names[self._next_player_idx]

    def reset(self):
        self._current_turn = 0
        self._next_player_idx = 0
        self._current_phase = DAY_DISSCUSION
        self.player_status = self.set_players_alive()
        self.set_player_roles(DEFAULT_DISTRIBUTION)
        self.night_vote_dict = self.reset_night_vote_dict()
        self.message_pool.reset()
        if len(sys.argv) > 0:
            self._get_reset_dicts(sys.argv[1])
        else:
            self._get_reset_dicts(DEFAULT_PROMPTS)
        self._initialized = True
        init_timestep = TimeStep(
            observation=self.get_observation(),
            reward=self.get_zero_rewards(),
            terminal=False,
        )
        return init_timestep

    def print(self):
        """Prints the message pool, I might want to see if I could store this
        in a file for records. """
        self.message_pool.print()

    def get_observation(self, player_name=None) -> List[Message]:
        """Get observation for the player."""
        """Individual players are explicitly reminded who is dead."""
        if player_name is None:
            return self.message_pool.get_all_messages()
        else:
            return self.message_pool.get_visible_messages(player_name, turn=self._current_turn)

    def step(self, player_name: str, action: str) -> TimeStep:
        """This is the action to result method so if they all vote and then a time step happens they learn the result and get rewards."""
        # Lets look deep at chameleon about how they handle their step and how that relates to the game.
        # Now I need to add full rules and role prompt as well.
        if (self._current_turn == 0):
            # Giving player their name and the rules of werewolf
            rule_name_promp =  + self._prompt_dict["rules_prompt"] + player_name
            self._moderator_speak(text= rule_name_promp, visible_to= player_name)
            # Giving player their role
            self._moderator_speak(text= self.player_roles[player_name][1], visible_to= player_name)
        if self._current_phase == DAY_DISSCUSION:
            #GIVE INFO ON WHO DIED. FIGURE OUT BEST DATA STRUCTURE FOR THIS.
            #Tally this after the night. 
            if self._discussion_count == 0:
                day_discuss_prompt =  self._prompt_dict["day_discuss_prompt"]
                self._moderator_speak(text= day_discuss_prompt)
            self._discussion_count += 1
            self.day_discuss_turn(player_name=player_name, action=action)
            if self._discussion_count >= self._discussion_max:
                self._discussion_count = 0
                self._current_phase = DAY_VOTE
        elif self._current_phase == DAY_VOTE:
            valid_votes = self.get_living_list().append("pass")
            vote_prompt = player_name + self._prompt_dict["day_vote_prompt"] + valid_votes
            self._moderator_speak(text= vote_prompt, visible_to= player_name)
            self.day_vote_turn(player_name=player_name, action=action)
        elif self._current_phase == NIGHT_DISSCUSION:
            night_discuss_prompt =  self._night_vote_prompts[self.player_roles[player_name][0]]
            self._moderator_speak(text= night_discuss_prompt, visible_to=self.werewolf_list)
            self.night_discuss_turn(player_name=player_name, action=action)
        elif self._current_phase == NIGHT_VOTE:
            self.night_vote_turn(player_name=player_name, action=action)
        terminal = self.is_terminal()
        timestep = TimeStep(
            observation=self.get_observation(), reward=self.get_rewards(terminal), terminal=terminal
        )
        if self.is_terminal():
            timestep.terminal = True

    def day_discuss_turn(self, player_name: str, action: str):
        """Day discuss phase turn for all roles."""
        self.message_pool.append_message(
            Message(agent_name=player_name, content=action, turn=self._current_turn)
            )
        
    def day_vote_turn(self, player_name: str, action: str):
        """Day vote phase turn for all roles."""
        message = Message(
            agent_name=player_name,
            content=action,
            turn=self._current_turn,
            visible_to= "all", #Check this I'm pretty sure this is valid.
        )
        self.message_pool.append_message(message) # Logs the who took the action and when, only visable to the current player in game.
        vote = self._text2vote(action)
        self.day_vote_dict[vote] += 1

    def night_discuss_turn(self, player_name: str, action: str):
        """Night discussion phase turn for special roles."""
        if (self.player_roles[player_name] == WEREWOLF):
            self.message_pool.append_message(
                Message(agent_name=player_name, content=action, turn=self._current_turn, visible_to=self.werewolf_list)
                )

    def night_vote_turn(self, player_name: str, action: str):
        """Night vote phase turn for special roles."""
        # Check if this is a special role, i.e. not basic townsfolk.
        if self.player_roles[player_name] == TOWNSFOLK: # Townsfolk don't have night actions.
            return
        else:
            message = Message(
                agent_name=player_name,
                content=action,
                turn=self._current_turn,
                visible_to=player_name,
            )
            self.message_pool.append_message(message) # Logs the who took the action and when, only visable to the current player in game.
            vote = self._text2vote(action)
            self.night_vote_dict[vote] = self.player_roles[player_name][0]

    def check_action(self, action: str, player_name: str) -> bool:
        """Checks if a action is valid."""
        return True

    def is_terminal(self) -> bool:
        """Checks if the game is over, for this that is a victory for werewolf or townsfolk"""
        town_count = 0
        werewolf_count = 0
        for player_name in self.player_status:
            if self.player_status[player_name] == ALIVE and self.player_roles[player_name][0] > WEREWOLF:
                town_count += 1
            elif self.player_status[player_name] == ALIVE and self.player_roles[player_name][0] == WEREWOLF:
                werewolf_count += 1
        if werewolf_count == 0 or town_count <= werewolf_count:
            return True
        return False

    def set_players_alive(self) -> Dict[str, float]:
        return {player_name: 1 for player_name in self.player_names}
    
    def set_player_roles(self, distribution) -> Dict[str, (float, str)]:
        player_roles = {}
        it = iter(self.player_names)
        random.shuffle(self.player_names)
        player_roles_distribution = [list(islice(it, 0, i)) for i in distribution]
        for i in range(0, len(player_roles_distribution)):
            for player in player_roles_distribution[i]:
                player_roles[player] = (i, self._distribution_text[i])
        self.player_roles = player_roles
        self.werewolf_list = []
        for player in player_roles:
            if player_roles[player] == WEREWOLF:
                self.werewolf_list.append(player)
    
    #Taken from Cameleon, a fairly heavy implementation, but gives leniency to response.
    def _text2vote(self, text) -> str:
        """Convert text to vote, return a player's name."""
        # bllower = text.lower().replace("[", "").replace("]", "").replace(".", "")
        text = text.lower()
        for name in self.player_names:
            candidates = [
                name.lower(),
                name.lower().replace(" ", ""),
                name.lower().replace(" ", "_"),
            ]
            if any([candidate in text for candidate in candidates]):
                return name
        return ""
    
    def reset_night_vote_dict(self):
        for player in self.player_names:
            self.night_vote_dict[player] = []

    def reset_day_vote_dict(self):
        for player in self.player_names:
            self.night_vote_dict[player] = 0
    
    #Currently gives no rewards
    def get_rewards(self, is_terminal):
        reward_dict = {}
        for player in self.player_names:
            reward_dict[player] = 0

    def get_living_list(self):
        living_list = []
        for player in self.player_status.keys():
            if self.player_status[player] == ALIVE:
                living_list.append(player)
        return living_list
    
    def _moderator_speak(self, text: str, visible_to: Union[str, List[str]] = "all"):
        """Moderator say something."""
        message = Message(
            agent_name="Moderator",
            content=text,
            turn=self._current_turn,
            visible_to=visible_to,
        )
        self.message_pool.append_message(message)

    def _get_prompt_dict(self, file_name):
        """Read the json for the prompts."""
        try:
            with open(file_name, 'r', encoding='utf-8') as file_object:
                self._prompt_dict =  json.load(file_object)
        except IOError:
            with open(DEFAULT_PROMPTS, 'r', encoding='utf-8') as file_object:
                self._prompt_dict = json.load(file_object)
        self._seer_reveal_prompts = [
            self._prompt_dict["seer_werewolf_prompt"],
            self._prompt_dict["seer_townsfolk_prompt"],
            self._prompt_dict["seer_seer_prompt"],
            self._prompt_dict["seer_guard_prompt"],
            self._prompt_dict["seer_witch_prompt"],
            self._prompt_dict["seer_hunter_prompt"]
        ]
        self._night_vote_prompts = [
            self._prompt_dict["night_vote_prompt_werewolf"],
            None,
            self._prompt_dict["night_vote_prompt_seer"],
            self._prompt_dict["night_vote_prompt_guard "],
            self._prompt_dict["night_vote_prompt_witch"],
            None
        ]
        self._distribution_text = [self._prompt_dict["werewolf_prompt"],
                        self._prompt_dict["townsfolk_prompt"],
                        self._prompt_dict["seer_prompt"],
                        self._prompt_dict["guard_prompt"],
                        self._prompt_dict["witch_prompt"],
                        self._prompt_dict["hunter_prompt"]]
        