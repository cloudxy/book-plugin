"""Synthetic v2 contract tests. These are not real author or model scores."""
from pathlib import Path
import copy
import shutil
import sys
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/persona-book'
sys.path.insert(0,str(ROOT/'bridge'))
from book_skill_common import (ContractError, DIMENSIONS, AUTHOR_DIMENSIONS, STYLE_DIMENSIONS,
    digest, read_json, read_yaml, write_json, input_snapshot, tree_hashes, verify_package)
from thinking_audit import validate, audit
from build_book_skill import build_candidate, publish
from eval_book_skill import prepare, collect, report_run, blind_packets


class AuthorContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='book-persona-test-')
        self.addCleanup(self.temp.cleanup)
        self.ws=Path(self.temp.name)
        self.book=self.ws/'books/persona-book'
        shutil.copytree(FIXTURE,self.book)
        self.source=ROOT/'tests/fixtures/thinking-source.md'
        self.modelpath=self.book/'thinking/model.yaml'

    def save(self,path,value):
        path.write_text(yaml.safe_dump(value,allow_unicode=True,sort_keys=False))

    def approve_fixture(self):
        data=validate(self.book,self.source)
        write_json(self.book/'eval/source-review.json',{'input_sha256':data['input_sha256'],
            'reviewer':'synthetic-reviewer','independent':True,
            'checks':{c:{'status':'passed','rationale':'SIMULATED CONTRACT ORACLE, NOT REAL SOURCE REVIEW'} for c in data['checks']}})

    def candidate(self):
        self.approve_fixture()
        return build_candidate(self.book,self.source,self.ws)

    def suite(self,normal_only=False,default_dimensions=False):
        cases=[{'id':f'C{i:02}','group':f'C{i:02}','prompt':'synthetic fixture user input',
            'rubric':['Synthetic oracle, not real task or score'], 'held_out':True,
            'expected_dimensions':list(DIMENSIONS+AUTHOR_DIMENSIONS),
            'author_targets':['H-conditions','P-assess','S-conditions'],
            'author_condition':'normal' if normal_only or i%2 else 'changed'} for i in range(1,16)]
        path=self.ws/'suite.yaml'
        if default_dimensions:
            for case in cases:
                case.pop('expected_dimensions')
        self.save(path,{'schema_version':'book-eval/2','cases':cases})
        return path

    def run_fixture(self,normal_only=False,default_dimensions=False):
        run=prepare(self.candidate(),self.suite(normal_only,default_dimensions),self.ws/'run')
        suite=read_json(run/'suite.json')
        hashes={}
        for case in suite['cases']:
            cid=case['id']
            answer='Synthetic fixture answer; not an actual model run.'
            output={'case_id':cid,'answers':[answer],'executor':'fixture-executor','host':'test-only',
                'model':'test-only','session_id':cid,'isolated':True,'loading_evidence':'synthetic test only'}
            path=self.ws/f'{cid}.json'
            write_json(path,output)
            collect(run,cid,path)
            hashes[cid]=digest(output)
            dimensions={d:{'score':2,'rationale':'SIMULATED TEST ORACLE'} for d in DIMENSIONS+AUTHOR_DIMENSIONS}
            for d in AUTHOR_DIMENSIONS:
                dimensions[d]['answer_excerpt']=answer
            write_json(run/'reviews'/f'{cid}.json',{'answer_sha256':digest(output),'rubric_sha256':digest(case),
                'reviewer':'fixture-behavior-reviewer','independent':True,'blind':True,
                'dimensions':dimensions,'expression':{d:{'score':2,'rationale':'SIMULATED TEST ORACLE'} for d in STYLE_DIMENSIONS},
                'author_evidence':{t:{'answer_excerpt':answer,'rationale':'SIMULATED TEST ORACLE'} for t in case['author_targets']},
                'hard_failures':[]})
        config=read_json(run/'run.json')
        write_json(run/'user-expression.json',{'build_id':config['build_id'],'suite_sha256':config['suite_sha256'],
            'output_sha256':hashes,'reviewer_role':'user','approved':True,'rationale':'SIMULATED USER FOR CONTRACT TEST ONLY'})
        return run

    def test_payload_and_generated_view_are_bound(self):
        candidate=self.candidate()
        manifest=verify_package(candidate)
        self.assertEqual(manifest['schema_version'],'book-skill/2')
        self.assertEqual(manifest['product_kind'],'author-persona')
        self.assertEqual(set(manifest['author_targets']),{'H-conditions','P-assess','S-conditions'})
        self.assertTrue((candidate/'references/reading/episodes.yaml').is_file())
        self.assertFalse(any('eval/' in x for x in manifest['files']))
        before=input_snapshot(self.book,self.source)
        (self.book/'AUTHOR_PROFILE.md').write_text('unsourced manual persona')
        self.assertEqual(input_snapshot(self.book,self.source),before)
        self.assertEqual(build_candidate(self.book,self.source,self.ws),candidate)
        self.assertEqual((self.book/'AUTHOR_PROFILE.md').read_bytes(),(candidate/'references/AUTHOR_PROFILE.md').read_bytes())
        manifest['schema_version']='book-skill/1'
        write_json(candidate/'book-workflow-manifest.json',manifest)
        with self.assertRaises(ContractError):
            verify_package(candidate)

    def test_v1_is_read_as_v1(self):
        legacy=self.ws/'books/legacy'
        shutil.copytree(ROOT/'tests/fixtures/thinking-book',legacy)
        data=validate(legacy,self.source)
        self.assertEqual(data['model']['schema_version'],'book-skill/1')
        self.assertEqual(data['author_targets'],{})
        self.assertNotIn('reading/episodes.yaml',data['snapshot']['files'])

    def test_episode_offsets_voice_and_links_are_checked(self):
        path=self.book/'reading/episodes.yaml'
        original=read_yaml(path)
        mutations=[lambda e:e.update(start=-1),lambda e:e.update(end=99999),
            lambda e:e.update(span_sha256='0'*64),lambda e:e.update(voice={'speaker':'unknown'}),
            lambda e:e.update(anchors=[]),lambda e:e.update(anchors=['missing'])]
        for mutate in mutations:
            changed=copy.deepcopy(original)
            mutate(changed['episodes'][0])
            self.save(path,changed)
            self.assertEqual(audit(self.book,self.source)['status'],'failed')
        self.save(path,original)
        path.unlink()
        self.assertEqual(audit(self.book,self.source)['status'],'failed')

    def test_new_claims_are_not_required_to_fill_a_novel(self):
        model=read_yaml(self.modelpath)
        model['claims']=[]; model['relations']=[]
        model['operators'][0]['uses']=['V-action','K-scope','H-conditions']
        self.save(self.modelpath,model)
        self.assertEqual(audit(self.book,self.source)['structural'],'passed')

    def test_persona_missing_and_unresolved_dependencies_fail(self):
        original=read_yaml(self.modelpath)
        for mutate in [lambda m:m.pop('author'),lambda m:m.update(habits=[]),lambda m:m.update(paths=[]),
                       lambda m:m['habits'][0].update(epistemic_status='unresolved'),
                       lambda m:m['paths'][0].update(operators=['missing'])]:
            changed=copy.deepcopy(original); mutate(changed); self.save(self.modelpath,changed)
            self.assertEqual(audit(self.book,self.source)['status'],'failed')

    def test_path_and_joint_examples_cannot_be_disconnected(self):
        model=read_yaml(self.modelpath)
        model['paths'][0]['expression']=['unknown-style']
        self.save(self.modelpath,model)
        self.assertEqual(audit(self.book,self.source)['status'],'failed')
        model['paths'][0]['expression']=['S-conditions']
        self.save(self.modelpath,model)
        path=self.book/'thinking/EXAMPLES.md'
        path.write_text(path.read_text().replace('- P-assess\n',''))
        self.assertEqual(audit(self.book,self.source)['status'],'failed')

    def test_episode_interpretation_change_invalidates_review(self):
        self.approve_fixture()
        path=self.book/'reading/episodes.yaml'
        episodes=read_yaml(path)
        episodes['episodes'][0]['progression']+=' changed interpretation'
        self.save(path,episodes)
        result=audit(self.book,self.source)
        self.assertEqual(result['status'],'failed')
        self.assertIn('stale',result['error'])

    def test_real_quote_and_span_do_not_override_failed_semantic_review(self):
        self.approve_fixture()
        path=self.book/'eval/source-review.json'
        review=read_json(path)
        review['checks']['episode:E-all']={'status':'failed',
            'rationale':'Synthetic review: offsets are real but the claimed reader effect is unsupported.'}
        write_json(path,review)
        self.assertEqual(audit(self.book,self.source)['status'],'failed')
        with self.assertRaises(ContractError):
            build_candidate(self.book,self.source,self.ws)

    def test_v2_suite_requires_authors_and_cannot_silently_use_v1(self):
        candidate=self.candidate()
        path=self.suite()
        original=read_yaml(path)
        for mutate in [lambda s:s.pop('schema_version'),
                       lambda s:s['cases'][0].update(expected_dimensions=list(DIMENSIONS)),
                       lambda s:s['cases'][1].update(task_type='lookup',applicability_reason='fake exception'),
                       lambda s:s['cases'][0].update(author_targets=['unknown'])]:
            suite=copy.deepcopy(original); mutate(suite); self.save(path,suite)
            with self.assertRaises(ContractError):
                prepare(candidate,path,self.ws/'rejected-run')
        self.assertFalse((self.ws/'rejected-run').exists())

    def test_author_low_missing_or_fabricated_evidence_blocks_acceptance(self):
        run=self.run_fixture()
        self.assertEqual(report_run(run)['status'],'passed')
        path=run/'reviews/C02.json'
        original=read_json(path)
        for mutate in [lambda r:r['dimensions']['author_cognition'].update(score=1),
                       lambda r:r['dimensions']['author_expression'].update(score=1),
                       lambda r:r['dimensions'].pop('author_expression'),
                       lambda r:r['dimensions']['author_expression'].update(answer_excerpt='fabricated quote'),
                       lambda r:r['author_evidence'].pop('P-assess')]:
            review=copy.deepcopy(original); mutate(review); write_json(path,review)
            self.assertEqual(report_run(run)['status'],'failed')

    def test_target_condition_coverage_is_separate_from_good_scores(self):
        run=self.run_fixture(normal_only=True)
        report=report_run(run)
        self.assertEqual(report['status'],'pending')
        self.assertTrue(any(p.startswith('author_target_coverage:') for p in report['pending']))

    def test_single_turn_defaults_do_not_invent_an_update_test(self):
        run=self.run_fixture(default_dimensions=True)
        for path in (run/'reviews').glob('*.json'):
            review=read_json(path)
            review['dimensions'].pop('updating')
            write_json(path,review)
        self.assertEqual(report_run(run)['status'],'passed')

    def test_manual_control_is_diagnostic_and_never_publishable(self):
        candidate=self.candidate()
        suite=self.suite()
        control=self.ws/'control'
        control.mkdir(); (control/'SKILL.md').write_text('Explicit synthetic summary control')
        with self.assertRaises(ContractError):
            prepare(candidate,suite,self.ws/'bad-control','summary',control)
        run=prepare(candidate,suite,self.ws/'control-run','ablation',control,mode='diagnostic',control_kind='without_habits')
        report=report_run(run)
        self.assertEqual(report['status'],'pending')
        self.assertEqual(read_json(run/'run.json')['control_kind'],'without_habits')
        write_json(run/'acceptance.json',report)
        with self.assertRaises(ContractError):
            publish(candidate,run/'acceptance.json',self.ws/'install')

    def test_blind_packets_preserve_whole_answers_and_hashes(self):
        run=self.run_fixture()
        out=blind_packets(run,self.ws/'blind')
        packet=read_json(next(out.glob('*.json')))
        original=read_json(run/'outputs'/f"{packet['case']['id']}.json")
        self.assertEqual(packet['answers'],original['answers'])
        self.assertEqual(packet['answer_sha256'],digest(original))
        self.assertEqual(packet['answers_sha256'],digest(original['answers']))
        self.assertNotIn('executor',packet)
        self.assertNotIn('variant',packet)

    def test_v2_exact_tested_payload_is_published(self):
        run=self.run_fixture()
        report=report_run(run)
        write_json(run/'acceptance.json',report)
        out=self.ws/'installed'
        publish(run/'skill',run/'acceptance.json',out)
        self.assertEqual(tree_hashes(run/'skill'),tree_hashes(out))


if __name__=='__main__':
    unittest.main()
