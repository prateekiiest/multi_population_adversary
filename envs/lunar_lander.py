import sys, math
import numpy as np

import Box2D
from Box2D.b2 import (edgeShape, circleShape, fixtureDef, polygonShape, revoluteJointDef, contactListener)

import gym
from gym import spaces
from gym.utils import seeding, EzPickle

from ray.rllib.env import MultiAgentEnv

# Rocket trajectory optimization is a classic topic in Optimal Control.
#
# According to Pontryagin's maximum principle it's optimal to fire engine full throttle or
# turn it off. That's the reason this environment is OK to have discreet actions (engine on or off).
#
# Landing pad is always at coordinates (0,0). Coordinates are the first two numbers in state vector.
# Reward for moving from the top of the screen to landing pad and zero speed is about 100..140 points.
# If lander moves away from landing pad it loses reward back. Episode finishes if the lander crashes or
# comes to rest, receiving additional -100 or +100 points. Each leg ground contact is +10. Firing main
# engine is -0.3 points each frame. Firing side engine is -0.03 points each frame. Solved is 200 points.
#
# Landing outside landing pad is possible. Fuel is infinite, so an agent can learn to fly and then land
# on its first attempt. Please see source code for details.
#
# To see heuristic landing, run:
#
# python gym/envs/box2d/lunar_lander.py
#
# To play yourself, run:
#
# python examples/agents/keyboard_agent.py LunarLander-v2
#
# Created by Oleg Klimov. Licensed on the same terms as the rest of OpenAI Gym.

FPS = 50
SCALE = 30.0  # affects how fast-paced the game is, forces should be adjusted as well

MAIN_ENGINE_POWER = 13.0
SIDE_ENGINE_POWER = 0.6

INITIAL_RANDOM = 1000.0  # Set 1500 to make game harder

LANDER_POLY = [
    (-14, +17), (-17, 0), (-17, -10),
    (+17, -10), (+17, 0), (+14, +17)
]
LEG_AWAY = 20
LEG_DOWN = 18
LEG_W, LEG_H = 2, 8
LEG_SPRING_TORQUE = 40

SIDE_ENGINE_HEIGHT = 14.0
SIDE_ENGINE_AWAY = 12.0

VIEWPORT_W = 600
VIEWPORT_H = 400


class ContactDetector(contactListener):
    def __init__(self, env):
        contactListener.__init__(self)
        self.env = env

    def BeginContact(self, contact):
        if self.env.lander == contact.fixtureA.body or self.env.lander == contact.fixtureB.body:
            self.env.game_over = True
        for i in range(2):
            if self.env.legs[i] in [contact.fixtureA.body, contact.fixtureB.body]:
                self.env.legs[i].ground_contact = True

    def EndContact(self, contact):
        for i in range(2):
            if self.env.legs[i] in [contact.fixtureA.body, contact.fixtureB.body]:
                self.env.legs[i].ground_contact = False


class LunarLander(MultiAgentEnv, EzPickle):
    metadata = {
        'render.modes': ['human', 'rgb_array'],
        'video.frames_per_second': FPS
    }

    continuous = False

    def __init__(self, config):
        EzPickle.__init__(self)
        self.seed()
        self.viewer = None
        self.main_engine_power = MAIN_ENGINE_POWER

        self.world = Box2D.b2World()
        self.moon = None
        self.lander = None
        self.particles = []

        self.prev_reward = None

        # useful range is -1 .. +1, but spikes can be higher
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(8,), dtype=np.float32)

        if self.continuous:
            # Action is two floats [main engine, left-right engines].
            # Main engine: -1..0 off, 0..+1 throttle from 50% to 100% power. Engine can't work with less than 50% power.
            # Left-right:  -1.0..-0.5 fire left engine, +0.5..+1.0 fire right engine, -0.5..0.5 off
            self.action_space = spaces.Box(-1, +1, (2,), dtype=np.float32)
        else:
            # Nop, fire left engine, main engine, right engine
            self.action_space = spaces.Discrete(4)

        self.total_reward = 0
        if len(config) > 0:

            self.num_adv_strengths = config["num_adv_strengths"]
            self.adversary_strength = config["adversary_strength"]
            # This sets how many adversaries exist per strength level
            self.advs_per_strength = config["advs_per_strength"]

            # This sets whether we should use adversaries across a reward range
            self.reward_range = config["reward_range"]
            # This sets the adversaries low reward range
            self.low_reward = config["low_reward"]
            # This sets wthe adversaries high reward range
            self.high_reward = config["high_reward"]

            # How frequently we check whether to increase the adversary range
            self.adv_incr_freq = config["adv_incr_freq"]
            # This checks whether we should have a curriculum at all
            self.curriculum = config["curriculum"]
            # The score we use for checking if it is time to increase the number of adversaries
            self.goal_score = config["goal_score"]
            # This is how many previous observations we concatenate to get the current observation
            self.num_concat_states = config["num_concat_states"]
            # This is whether we concatenate the agent action into the observation
            self.concat_actions = config["concat_actions"]
            # This is whether we concatenate the agent action into the observation
            self.domain_randomization = config["domain_randomization"]
            self.cheating = config["cheating"]
            # whether the adversaries are receiving penalties for being too similar
            self.l2_reward = config['l2_reward']
            self.kl_reward = config['kl_reward']
            self.l2_in_tranche = config['l2_in_tranche']
            self.l2_memory = config['l2_memory']
            self.l2_memory_target_coeff = config['l2_memory_target_coeff']
            self.l2_reward_coeff = config['l2_reward_coeff']
            self.kl_reward_coeff = config['kl_reward_coeff']
            self.end_if_fall = config['end_if_fall']

            # here we note that num_adversaries includes the num adv per strength so if we don't divide by this
            # then we are double counting
            self.strengths = np.linspace(start=0, stop=1,
                                         num=self.num_adv_strengths + 1)[1:]
            # repeat the bins so that we can index the adversaries easily
            self.strengths = np.repeat(self.strengths, self.advs_per_strength)

            # index we use to track how many iterations we have maintained above the goal score
            self.num_iters_above_goal_score = 0

            # This tracks how many adversaries are turned on
            if self.curriculum:
                self.adversary_range = 0
            else:
                self.adversary_range = self.num_adv_strengths * self.advs_per_strength
            if self.adversary_range > 0:
                self.curr_adversary = np.random.randint(low=0, high=self.adversary_range)
            else:
                self.curr_adversary = 0

            # Every adversary at a strength level has different targets. This spurs them to
            # pursue different strategies
            self.num_adv_rews = config['num_adv_rews']
            self.advs_per_rew = config['advs_per_rew']
            self.reward_targets = np.linspace(start=self.low_reward, stop=self.high_reward,
                                              num=self.num_adv_rews)
            # repeat the bins so that we can index the adversaries easily
            self.reward_targets = np.repeat(self.reward_targets, self.advs_per_rew)

            self.comp_adversaries = []
            for i in range(self.adversary_range):
                curr_tranche = int(i / self.num_adv_strengths)
                low_range = max(curr_tranche * self.num_adv_strengths, i - self.num_adv_strengths)
                high_range = min((curr_tranche + 1) * self.num_adv_strengths, i + self.num_adv_strengths)
                self.comp_adversaries.append([low_range, high_range])

            # used to track the previously observed states to induce a memory
            # TODO(@evinitsky) bad hardcoding
            self.obs_size = 11
            if self.cheating:
                self.obs_size += 2
                self.friction_coef = 1.0
                self.mass_coef = 1.0
            self.num_actions = 3
            if self.concat_actions:
                self.obs_size += self.num_actions
            self.observed_states = np.zeros(self.obs_size * self.num_concat_states)

            # instantiate the l2 memory tracker
            if self.adversary_range > 0 and self.l2_memory:
                self.global_l2_memory_array = np.zeros(
                    (self.adversary_range, self.adv_action_space.low.shape[0], self.horizon + 1))
                self.local_l2_memory_array = np.zeros(
                    (self.adversary_range, self.adv_action_space.low.shape[0], self.horizon + 1))
                self.local_num_observed_l2_samples = np.zeros(self.adversary_range)

        self.reset()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def _destroy(self):
        if not self.moon: return
        self.world.contactListener = None
        self._clean_particles(True)
        self.world.DestroyBody(self.moon)
        self.moon = None
        self.world.DestroyBody(self.lander)
        self.lander = None
        self.world.DestroyBody(self.legs[0])
        self.world.DestroyBody(self.legs[1])

    def reset(self):
        self._destroy()
        self.world.contactListener_keepref = ContactDetector(self)
        self.world.contactListener = self.world.contactListener_keepref
        self.game_over = False
        self.prev_shaping = None

        W = VIEWPORT_W / SCALE
        H = VIEWPORT_H / SCALE

        # terrain
        CHUNKS = 11
        height = self.np_random.uniform(0, H / 2, size=(CHUNKS + 1,))
        chunk_x = [W / (CHUNKS - 1) * i for i in range(CHUNKS)]
        self.helipad_x1 = chunk_x[CHUNKS // 2 - 1]
        self.helipad_x2 = chunk_x[CHUNKS // 2 + 1]
        self.helipad_y = H / 4
        height[CHUNKS // 2 - 2] = self.helipad_y
        height[CHUNKS // 2 - 1] = self.helipad_y
        height[CHUNKS // 2 + 0] = self.helipad_y
        height[CHUNKS // 2 + 1] = self.helipad_y
        height[CHUNKS // 2 + 2] = self.helipad_y
        smooth_y = [0.33 * (height[i - 1] + height[i + 0] + height[i + 1]) for i in range(CHUNKS)]

        self.moon = self.world.CreateStaticBody(shapes=edgeShape(vertices=[(0, 0), (W, 0)]))
        self.sky_polys = []
        for i in range(CHUNKS - 1):
            p1 = (chunk_x[i], smooth_y[i])
            p2 = (chunk_x[i + 1], smooth_y[i + 1])
            self.moon.CreateEdgeFixture(
                vertices=[p1, p2],
                density=0,
                friction=0.1)
            self.sky_polys.append([p1, p2, (p2[0], H), (p1[0], H)])

        self.moon.color1 = (0.0, 0.0, 0.0)
        self.moon.color2 = (0.0, 0.0, 0.0)

        initial_y = VIEWPORT_H / SCALE
        self.lander = self.world.CreateDynamicBody(
            position=(VIEWPORT_W / SCALE / 2, initial_y),
            angle=0.0,
            fixtures=fixtureDef(
                shape=polygonShape(vertices=[(x / SCALE, y / SCALE) for x, y in LANDER_POLY]),
                density=5.0,
                friction=0.1,
                categoryBits=0x0010,
                maskBits=0x001,  # collide only with ground
                restitution=0.0)  # 0.99 bouncy
        )
        self.lander.color1 = (0.5, 0.4, 0.9)
        self.lander.color2 = (0.3, 0.3, 0.5)
        self.lander.ApplyForceToCenter((
            self.np_random.uniform(-INITIAL_RANDOM, INITIAL_RANDOM),
            self.np_random.uniform(-INITIAL_RANDOM, INITIAL_RANDOM)
        ), True)

        self.legs = []
        for i in [-1, +1]:
            leg = self.world.CreateDynamicBody(
                position=(VIEWPORT_W / SCALE / 2 - i * LEG_AWAY / SCALE, initial_y),
                angle=(i * 0.05),
                fixtures=fixtureDef(
                    shape=polygonShape(box=(LEG_W / SCALE, LEG_H / SCALE)),
                    density=1.0,
                    restitution=0.0,
                    categoryBits=0x0020,
                    maskBits=0x001)
            )
            leg.ground_contact = False
            leg.color1 = (0.5, 0.4, 0.9)
            leg.color2 = (0.3, 0.3, 0.5)
            rjd = revoluteJointDef(
                bodyA=self.lander,
                bodyB=leg,
                localAnchorA=(0, 0),
                localAnchorB=(i * LEG_AWAY / SCALE, LEG_DOWN / SCALE),
                enableMotor=True,
                enableLimit=True,
                maxMotorTorque=LEG_SPRING_TORQUE,
                motorSpeed=+0.3 * i  # low enough not to jump back into the sky
            )
            if i == -1:
                rjd.lowerAngle = +0.9 - 0.5  # Yes, the most esoteric numbers here, angles legs have freedom to travel within
                rjd.upperAngle = +0.9
            else:
                rjd.lowerAngle = -0.9
                rjd.upperAngle = -0.9 + 0.5
            leg.joint = self.world.CreateJoint(rjd)
            self.legs.append(leg)

        self.drawlist = [self.lander] + self.legs

        return self.step({'agent': np.array([0, 0]) if self.continuous else 0})[0]

    def _create_particle(self, mass, x, y, ttl):
        p = self.world.CreateDynamicBody(
            position=(x, y),
            angle=0.0,
            fixtures=fixtureDef(
                shape=circleShape(radius=2 / SCALE, pos=(0, 0)),
                density=mass,
                friction=0.1,
                categoryBits=0x0100,
                maskBits=0x001,  # collide only with ground
                restitution=0.3)
        )
        p.ttl = ttl
        self.particles.append(p)
        self._clean_particles(False)
        return p

    def _clean_particles(self, all):
        while self.particles and (all or self.particles[0].ttl < 0):
            self.world.DestroyBody(self.particles.pop(0))

    def step(self, dict_action):
        if self.continuous:
            action = np.clip(dict_action['agent'], -1, +1).astype(np.float32)
        else:
            action = dict_action['agent']

        # Engines
        tip = (math.sin(self.lander.angle), math.cos(self.lander.angle))
        side = (-tip[1], tip[0])
        dispersion = [self.np_random.uniform(-1.0, +1.0) / SCALE for _ in range(2)]

        m_power = 0.0
        if (self.continuous and action[0] > 0.0) or (not self.continuous and action == 2):
            # Main engine
            if self.continuous:
                m_power = (np.clip(action[0], 0.0, 1.0) + 1.0) * 0.5  # 0.5..1.0
                assert m_power >= 0.5 and m_power <= 1.0
            else:
                m_power = 1.0
            ox = tip[0] * (4 / SCALE + 2 * dispersion[0]) + side[0] * dispersion[
                1]  # 4 is move a bit downwards, +-2 for randomness
            oy = -tip[1] * (4 / SCALE + 2 * dispersion[0]) - side[1] * dispersion[1]
            impulse_pos = (self.lander.position[0] + ox, self.lander.position[1] + oy)
            p = self._create_particle(3.5, impulse_pos[0], impulse_pos[1],
                                      m_power)  # particles are just a decoration, 3.5 is here to make particle speed adequate
            p.ApplyLinearImpulse((ox * self.main_engine_power * m_power, oy * self.main_engine_power * m_power), impulse_pos,
                                 True)
            self.lander.ApplyLinearImpulse((-ox * self.main_engine_power * m_power, -oy * self.main_engine_power * m_power),
                                           impulse_pos, True)

        s_power = 0.0
        if (self.continuous and np.abs(action[1]) > 0.5) or (not self.continuous and action in [1, 3]):
            # Orientation engines
            if self.continuous:
                direction = np.sign(action[1])
                s_power = np.clip(np.abs(action[1]), 0.5, 1.0)
                assert s_power >= 0.5 and s_power <= 1.0
            else:
                direction = action - 2
                s_power = 1.0
            ox = tip[0] * dispersion[0] + side[0] * (3 * dispersion[1] + direction * SIDE_ENGINE_AWAY / SCALE)
            oy = -tip[1] * dispersion[0] - side[1] * (3 * dispersion[1] + direction * SIDE_ENGINE_AWAY / SCALE)
            impulse_pos = (self.lander.position[0] + ox - tip[0] * 17 / SCALE,
                           self.lander.position[1] + oy + tip[1] * SIDE_ENGINE_HEIGHT / SCALE)
            p = self._create_particle(0.7, impulse_pos[0], impulse_pos[1], s_power)
            p.ApplyLinearImpulse((ox * SIDE_ENGINE_POWER * s_power, oy * SIDE_ENGINE_POWER * s_power), impulse_pos,
                                 True)
            self.lander.ApplyLinearImpulse((-ox * SIDE_ENGINE_POWER * s_power, -oy * SIDE_ENGINE_POWER * s_power),
                                           impulse_pos, True)

        self.world.Step(1.0 / FPS, 6 * 30, 2 * 30)

        pos = self.lander.position
        vel = self.lander.linearVelocity
        state = [
            (pos.x - VIEWPORT_W / SCALE / 2) / (VIEWPORT_W / SCALE / 2),
            (pos.y - (self.helipad_y + LEG_DOWN / SCALE)) / (VIEWPORT_H / SCALE / 2),
            vel.x * (VIEWPORT_W / SCALE / 2) / FPS,
            vel.y * (VIEWPORT_H / SCALE / 2) / FPS,
            self.lander.angle,
            20.0 * self.lander.angularVelocity / FPS,
            1.0 if self.legs[0].ground_contact else 0.0,
            1.0 if self.legs[1].ground_contact else 0.0
        ]
        assert len(state) == 8

        reward = 0
        shaping = \
            - 100 * np.sqrt(state[0] * state[0] + state[1] * state[1]) \
            - 100 * np.sqrt(state[2] * state[2] + state[3] * state[3]) \
            - 100 * abs(state[4]) + 10 * state[6] + 10 * state[7]  # And ten points for legs contact, the idea is if you
        # lose contact again after landing, you get negative reward
        if self.prev_shaping is not None:
            reward = shaping - self.prev_shaping
        self.prev_shaping = shaping

        reward -= m_power * 0.30  # less fuel spent is better, about -30 for heurisic landing
        reward -= s_power * 0.03

        done = False
        if self.game_over or abs(state[0]) >= 1.0:
            done = True
            reward = -100
        if not self.lander.awake:
            done = True
            reward = +100
        return {'agent': np.array(state, dtype=np.float32)}, {'agent': reward}, {'__all__': done}, {}

    def render(self, mode='human'):
        from gym.envs.classic_control import rendering
        if self.viewer is None:
            self.viewer = rendering.Viewer(VIEWPORT_W, VIEWPORT_H)
            self.viewer.set_bounds(0, VIEWPORT_W / SCALE, 0, VIEWPORT_H / SCALE)

        for obj in self.particles:
            obj.ttl -= 0.15
            obj.color1 = (max(0.2, 0.2 + obj.ttl), max(0.2, 0.5 * obj.ttl), max(0.2, 0.5 * obj.ttl))
            obj.color2 = (max(0.2, 0.2 + obj.ttl), max(0.2, 0.5 * obj.ttl), max(0.2, 0.5 * obj.ttl))

        self._clean_particles(False)

        for p in self.sky_polys:
            self.viewer.draw_polygon(p, color=(0, 0, 0))

        for obj in self.particles + self.drawlist:
            for f in obj.fixtures:
                trans = f.body.transform
                if type(f.shape) is circleShape:
                    t = rendering.Transform(translation=trans * f.shape.pos)
                    self.viewer.draw_circle(f.shape.radius, 20, color=obj.color1).add_attr(t)
                    self.viewer.draw_circle(f.shape.radius, 20, color=obj.color2, filled=False, linewidth=2).add_attr(t)
                else:
                    path = [trans * v for v in f.shape.vertices]
                    self.viewer.draw_polygon(path, color=obj.color1)
                    path.append(path[0])
                    self.viewer.draw_polyline(path, color=obj.color2, linewidth=2)

        for x in [self.helipad_x1, self.helipad_x2]:
            flagy1 = self.helipad_y
            flagy2 = flagy1 + 50 / SCALE
            self.viewer.draw_polyline([(x, flagy1), (x, flagy2)], color=(1, 1, 1))
            self.viewer.draw_polygon([(x, flagy2), (x, flagy2 - 10 / SCALE), (x + 25 / SCALE, flagy2 - 5 / SCALE)],
                                     color=(0.8, 0.8, 0))

        return self.viewer.render(return_rgb_array=mode == 'rgb_array')

    def close(self):
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None


class LunarLanderContinuous(LunarLander):
    continuous = True


def heuristic(env, s):
    # Heuristic for:
    # 1. Testing.
    # 2. Demonstration rollout.
    angle_targ = s[0] * 0.5 + s[
        2] * 1.0  # angle should point towards center (s[0] is horizontal coordinate, s[2] hor speed)
    if angle_targ > 0.4: angle_targ = 0.4  # more than 0.4 radians (22 degrees) is bad
    if angle_targ < -0.4: angle_targ = -0.4
    hover_targ = 0.55 * np.abs(s[0])  # target y should be proporional to horizontal offset

    # PID controller: s[4] angle, s[5] angularSpeed
    angle_todo = (angle_targ - s[4]) * 0.5 - (s[5]) * 1.0
    # print("angle_targ=%0.2f, angle_todo=%0.2f" % (angle_targ, angle_todo))

    # PID controller: s[1] vertical coordinate s[3] vertical speed
    hover_todo = (hover_targ - s[1]) * 0.5 - (s[3]) * 0.5
    # print("hover_targ=%0.2f, hover_todo=%0.2f" % (hover_targ, hover_todo))

    if s[6] or s[7]:  # legs have contact
        angle_todo = 0
        hover_todo = -(s[3]) * 0.5  # override to reduce fall speed, that's all we need after contact

    if env.continuous:
        a = np.array([hover_todo * 20 - 1, -angle_todo * 20])
        a = np.clip(a, -1, +1)
    else:
        a = 0
        if hover_todo > np.abs(angle_todo) and hover_todo > 0.05:
            a = 2
        elif angle_todo < -0.05:
            a = 3
        elif angle_todo > +0.05:
            a = 1
    print(a)
    return a


def demo_heuristic_lander(env, seed=None, render=False):
    env.seed(seed)
    total_reward = 0
    steps = 0
    s = env.reset()
    while True:
        a = heuristic(env, s['agent'])
        s, r, done, info = env.step({'agent': a})
        total_reward += r['agent']

        if render:
            still_open = env.render()
            if still_open == False: break

        if steps % 20 == 0 or done['__all__']:
            print("observations:", " ".join(["{:+0.2f}".format(x) for x in s['agent']]))
            print("step {} total_reward {:+0.2f}".format(steps, total_reward))
        steps += 1
        if done['__all__']: break
    return total_reward


if __name__ == '__main__':
    demo_heuristic_lander(LunarLander({}), render=True)