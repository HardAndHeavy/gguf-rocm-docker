"""CPU-only process-plan controls for forced-bus revision comparisons."""
import importlib.util
from pathlib import Path
import unittest
SPEC = importlib.util.spec_from_file_location('pool_ab', Path(__file__).resolve().parents[1]/'scripts/run-colibri-pool-ab.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

class ComparisonPlanTests(unittest.TestCase):
    def test_interleaved_images_all_bus(self):
        plan = runner.bus_comparison_plan('old-id', 'new-id')
        self.assertEqual([p['image'] for p in plan], ['old-id','new-id','new-id','old-id'])
        self.assertEqual([p['build'] for p in plan], ['old','new','new','old'])
        self.assertEqual([p['profile'] for p in plan], ['B']*4)

    def test_plan_dictionaries_do_not_alias(self):
        plan = runner.bus_comparison_plan('o','n')
        plan[1]['profile']='changed'
        self.assertEqual(plan[2]['profile'], 'B')

    def test_legacy_defaults_remain_unset(self):
        for profile in 'ABC':
            env = runner.process_environment(profile)
            self.assertNotIn('COLI_CUDA_GEMV_SK', env)
            self.assertNotIn('COLI_CUDA_CHAIN_PROMOTE', env)
            self.assertEqual(env.get('COLI_CUDA_CHAIN_POOL_READ'), None if profile == 'A' else '1')
        self.assertEqual(runner.process_environment('C')['COLI_CUDA_CHAIN_PROMOTE_HITS'], '90')

    def test_explicit_settings_reach_docker_arguments(self):
        for value in ('0','1'):
            env = runner.process_environment('B', value, value)
            args = runner.environment_arguments(env)
            for key in ('COLI_CUDA_GEMV_SK', 'COLI_CUDA_CHAIN_PROMOTE'):
                self.assertEqual(env[key], value)
                index = args.index(key+'='+value)
                self.assertEqual(args[index-1], '-e')
            self.assertEqual(env['COLI_CUDA_CHAIN_POOL_READ'], '1')
            self.assertEqual(env['Q38_MTP'], '0')

    def test_resume_settings_legacy_and_explicit(self):
        runner.check_resume_settings({}, runner.experiment_settings())
        settings = runner.experiment_settings('0','0')
        runner.check_resume_settings({'experiment_settings': settings}, settings)
        for previous in ({}, {'experiment_settings': runner.experiment_settings('1','0')}):
            with self.assertRaisesRegex(RuntimeError, 'settings mismatch'):
                runner.check_resume_settings(previous, settings)

    def test_scratch_comparison_same_image_and_only_limit_differs(self):
        plan = runner.scratch_comparison_plan('immutable')
        self.assertEqual([p['image'] for p in plan], ['immutable']*4)
        self.assertEqual([p['profile'] for p in plan], ['B']*4)
        self.assertEqual([p['scratch_limit'] for p in plan], [None, '1073741824', '1073741824', None])
        baseline = runner.process_environment('B', '0', '0')
        self.assertNotIn('HSA_SCRATCH_SINGLE_LIMIT', baseline)
        changed = runner.process_environment('B', '0', '0', plan[1]['scratch_limit'])
        docker_args = runner.environment_arguments(changed)
        index = docker_args.index('HSA_SCRATCH_SINGLE_LIMIT=1073741824')
        self.assertEqual(docker_args[index-1], '-e')
        self.assertEqual(changed.pop('HSA_SCRATCH_SINGLE_LIMIT'), '1073741824')
        self.assertEqual(changed, baseline)
        plan[1]['scratch_limit'] = 'changed'
        self.assertEqual(plan[2]['scratch_limit'], '1073741824')
