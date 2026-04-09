class RWModel:
    def __init__(
        self,
        alpha=0.5,
        element_cues=None,
        configural_cues=None,
        replaced_cues=None,
        replaced_rules=None,
        initial_weight=0.2,
        debug=False,
    ):
        self.alpha = alpha
        self.debug = debug

        self.weight = {
            cue: initial_weight for cue in (element_cues or [])
        }

        self.configural_weights = {
            cue: initial_weight for cue in (configural_cues or [])
        }

        self.replaced_weights = {
            cue: initial_weight for cue in (replaced_cues or [])
        }

        self.replaced_rules = replaced_rules or []

    def make_configural_name(self, cue1, cue2):
        pair = sorted([cue1, cue2])
        return pair[0] + "+" + pair[1]

    def get_configural_cues(self, active_cues: list):
        pairs = []

        for i in range(len(active_cues)):
            for j in range(i + 1, len(active_cues)):
                name = self.make_configural_name(active_cues[i], active_cues[j])
                if name in self.configural_weights:
                    pairs.append(name)

        return pairs

    def get_replaced_cues(self, active_cues: list):
        replaced = []

        for rule in self.replaced_rules:
            required_cues = rule.get("when", [])
            replaced_name = rule.get("replace_with")

            if replaced_name in self.replaced_weights and all(cue in active_cues for cue in required_cues):
                replaced.append(replaced_name)

        return replaced

    def predict(self, active_cues: list):
        configural_cues = self.get_configural_cues(active_cues)
        replaced_cues = self.get_replaced_cues(active_cues)

        values = []

        for cue in active_cues:
            if cue in self.weight:
                values.append(self.weight[cue])

        for cue in configural_cues:
            values.append(self.configural_weights[cue])

        for cue in replaced_cues:
            values.append(self.replaced_weights[cue])

        if not values:
            return 0.0

        return sum(values) / len(values)

    def update(self, active_cues: list, reward, next_prediction, gamma=0.9):
        current_prediction = self.predict(active_cues)
        td_error = reward + gamma * next_prediction - current_prediction

        for cue in active_cues:
            if cue in self.weight:
                self.weight[cue] += self.alpha * td_error

        for cue in self.get_configural_cues(active_cues):
            self.configural_weights[cue] += self.alpha * td_error

        for cue in self.get_replaced_cues(active_cues):
            self.replaced_weights[cue] += self.alpha * td_error

        if self.debug:
            print("current_prediction:", round(current_prediction, 3))
            print("reward:", reward)
            print("next_prediction:", round(next_prediction, 3))
            print("td_error:", round(td_error, 3))