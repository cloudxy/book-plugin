"""Synthetic contracts for production; these tests do not measure book quality."""
from pathlib import Path
import copy
import json
import shutil
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bridge'))
import production as p
import production_eval as ev
import distill_skill as ds
import skill_portfolio as port
from production_common import atomic_json
from book_skill_common import ContractError,read_json


def executor(name):
    return {'host':'synthetic-test','model':'no-model','session_id':name}


def result(packet):
    stage=packet['stage']
    if stage in {'read','merge'}:
        units=[packet['task_id']] if stage=='read' else [u for r in packet['inputs'].values() for u in r['covered_units']]
        return {'covered_units':units,'findings':'Synthetic: separate observation from explanation, specify conditions before trying a reversible change.','limitations':['Synthetic fixture only'],'open_connections':[]}
    if stage=='synthesize':
        return {'schema_version':ds.MODEL_SCHEMA,'description':'Use for reversible choices with uncertain evidence.','core':'State the prediction and conditions before trying a reversible change.','uses':['Explain conditional decisions'],'limits':['Synthetic fixture; no quality evidence'],
                'capabilities':[{'id':'conditional','kind':'knowledge','name':'Conditional evidence','trigger':'Uncertain reversible choice','actions':['Specify prediction','Observe before generalizing'],'conditions':['Change is reversible'],'changes':['Irreversible cost requires other evidence'],'evidence':packet['source_units'],'epistemic_status':'reconstructed'}],
                'examples':[{'id':'shop','capabilities':['conditional'],'task':'Extend hours?','answer':'Try one evening and measure costs.','changed_task':'A year-long contract is required.','changed_answer':'Seek existing demand evidence first.','origin':'synthetic'}],
                'procedures':{'status':'not_applicable','reason':'Explanatory capability, no executable procedure'}}
    if stage=='review':
        return {'verdict':'pass','decisions':{i['id']:{'verdict':'pass','reason':'Synthetic control-flow fixture.'} for i in packet['inputs']['synthesize']['capabilities']+packet['inputs']['synthesize']['examples']},'issues':[],'coverage_assessment':'Synthetic, not real source review.'}
    raise AssertionError(stage)


class ProductionContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='production-contract-');self.addCleanup(self.temp.cleanup)
        self.ws=Path(self.temp.name);self.root=self.ws/'pipeline';self.src=self.ws/'source.txt'
        self.src.write_text(('Synthetic source: conditions before conclusions. Reversible trials can inform action.\n'*12))
        self.product={'id':'synthetic','object':'book','title':'Synthetic','period':'v1','purpose':'Contract tests','profiles':['knowledge']}
        p.init(self.root,[{'path':str(self.src),'role':'synthetic','period':'v1'}],self.product,{'chunk_chars':200,'merge_fanout':2})

    def finish(self):
        while (packet:=p.claim(self.root,'test')):
            data=ds.build(self.root,p.read_state(self.root)) if packet['stage']=='build' else result(packet)
            p.collect(self.root,packet['task_id'],packet['claim_token'],data,executor(packet['claim_token']))
        return p.status(self.root)

    def evaluated(self):
        built=self.finish();candidate=self.root/built['package']
        suite={'schema_version':'production-eval/1','cases':[{'id':g,'group':g,'turns':['Explain this uncertain choice.']+(['The choice is now irreversible.'] if g=='correction' else []),'rubric':'Synthetic review only.','targets':['conditional'],'condition':'changed' if g=='changed' else 'normal','held_out':g=='changed'} for g in sorted(ev.GROUPS)]}
        path=self.ws/'suite.json';atomic_json(path,suite);run=self.ws/'evaluation'
        ev.prepare(candidate,path,run,{'text':self.src.read_text()})
        self.assertEqual(ev.report(run)['status'],'pending')
        for case in suite['cases']:
            for i in range(len(case['turns'])):
                ev.collect_answer(run,case['id'],i,{'result':{'answer':'Specify the conditions before drawing a conclusion.'},'executor':executor(case['id']+str(i))})
            ev.collect_review(run,case['id'],{'result':{'dimensions':{d:{'score':2,'reason':'Synthetic evidence.','excerpt':'Specify the conditions'} for d in ev.DIMENSIONS},'hard_failures':[]},'executor':executor('review-'+case['id'])})
        self.assertEqual(ev.report(run)['status'],'passed')
        return candidate,run,suite

    def test_complete_read_ranges_and_no_semantic_claim(self):
        state=p.read_state(self.root);ranges=sorted((u['start'],u['end']) for u in state['units'].values())
        self.assertEqual(ranges[0][0],0);self.assertEqual(ranges[-1][1],len(self.src.read_text()))
        self.assertTrue(all(a[1]==b[0] for a,b in zip(ranges,ranges[1:])))
        self.assertEqual(p.status(self.root)['status'],'pending')

    def test_claim_cap_and_expired_results(self):
        a=p.claim(self.root,'a');b=p.claim(self.root,'b');self.assertIsNone(p.claim(self.root,'c'))
        state=p.read_state(self.root);state['tasks'][a['task_id']]['lease']['until']=time.time()-1;p.save(self.root,state)
        c=p.claim(self.root,'c',a['task_id'])
        with self.assertRaises(ContractError):p.collect(self.root,a['task_id'],a['claim_token'],result(a),executor('old'))
        p.collect(self.root,c['task_id'],c['claim_token'],result(c),executor('new'))

    def test_failure_budget_and_resume(self):
        a=p.claim(self.root,'a')
        p.collect(self.root,a['task_id'],a['claim_token'],{},executor('fail'),error='transient')
        b=p.claim(self.root,'b',a['task_id']);self.assertEqual(b['attempt'],2)
        p.collect(self.root,b['task_id'],b['claim_token'],result(b),executor('ok'))
        self.assertEqual(self.finish()['status'],'built-pending-runtime')

    def test_changed_source_reuses_unaffected_units(self):
        self.finish();self.src.write_text(self.src.read_text().replace('Synthetic','Xynthetic',1))
        self.assertEqual(p.status(self.root)['status'],'stale-source')
        p.sync(self.root);state=p.read_state(self.root)
        reads=[t for t in state['tasks'].values() if t['kind']=='read']
        self.assertEqual(sum(t['status']=='stale' for t in reads),1)
        self.assertTrue(any(t['status']=='done' for t in reads))
        self.assertEqual(state['tasks']['build']['status'],'stale')

    def test_stage_tamper_propagates_in_one_status(self):
        self.finish();state=p.read_state(self.root);t=next(t for t in state['tasks'].values() if t['kind']=='read')
        path=self.root/t['output'];data=read_json(path);data['result']['findings']='Changed';atomic_json(path,data)
        self.assertEqual(p.status(self.root)['tasks']['build']['status'],'stale')

    def test_corrupt_package_quarantined_and_rebuilt(self):
        built=self.finish();entry=self.root/built['package']/'SKILL.md';entry.write_text('corrupt')
        self.assertEqual(self.finish()['status'],'built-pending-runtime')
        self.assertTrue(list((self.root/'quarantine').iterdir()))
        ds.verify(self.root/p.status(self.root)['package'])

    def test_source_review_requires_other_session(self):
        while (a:=p.claim(self.root,'test')):
            if a['stage']=='review':break
            p.collect(self.root,a['task_id'],a['claim_token'],result(a),executor('generator'))
        out=p.collect(self.root,a['task_id'],a['claim_token'],result(a),executor('generator'))
        self.assertIn('independent',out['error'])

    def test_budget_stops_without_false_completion(self):
        state=p.read_state(self.root);state['policy']['max_calls']=1;p.save(self.root,state)
        a=p.claim(self.root,'a');p.collect(self.root,a['task_id'],a['claim_token'],result(a),executor('a'))
        self.assertIsNone(p.claim(self.root,'b'));self.assertIn('budget',p.status(self.root)['stop_reason'])

    def test_future_turn_and_rubric_hidden(self):
        candidate,run,suite=self.evaluated();packet=ev.answer_packet(run,'correction',0)
        self.assertEqual(len(packet['conversation']),1);self.assertNotIn('rubric',packet)
        self.assertNotIn('irreversible',json.dumps(packet))

    def test_valid_score_edit_cannot_promote(self):
        candidate,run,_=self.evaluated();path=run/'reviews/direct.json';data=read_json(path)
        data['result']['dimensions']['utility']['score']=3;atomic_json(path,data)
        with self.assertRaises(ContractError):ev.report(run)
        with self.assertRaises(ContractError):port.register(self.ws,candidate,run)

    def test_target_and_host_tamper_rejected(self):
        candidate,run,_=self.evaluated();config=read_json(run/'config.json');edited=copy.deepcopy(config);edited['targets']=[]
        atomic_json(run/'config.json',edited)
        with self.assertRaises(ContractError):ev.report(run)
        atomic_json(run/'config.json',config);atomic_json(run/'answers/unknown/0.json',{'executor':executor('fake')})
        with self.assertRaises(ContractError):ev.report(run)

    def test_portable_export_and_metadata_tamper(self):
        candidate,run,_=self.evaluated();port.register(self.ws,candidate,run);out=self.ws/'export';port.export(self.ws,out)
        shutil.move(self.root,self.ws/'unavailable');shutil.move(run,self.ws/'eval-unavailable')
        self.assertEqual(len(port.verify_portfolio(out)['entries']),1)
        path=out/'PORTFOLIO.json';data=read_json(path);data['entries'][0]['outputs']=['invented'];atomic_json(path,data)
        with self.assertRaises(ContractError):port.verify_portfolio(out)

    def test_empty_sources_and_identity_leak(self):
        built=self.finish();candidate=self.root/built['package']
        with self.assertRaises(ContractError):ev.clean_sources({})
        self.assertEqual(ev.clean_sources({'text':'source','executor':{'session':'secret'}}),{'documents':[{'text':'source'}]})

    def test_prompt_change_invalidates_only_downstream(self):
        self.finish();state=p.read_state(self.root);prompts=read_json(p.PROMPTS);prompts['synthesize']+=' Explicit change.'
        path=self.ws/'prompts.json';atomic_json(path,prompts);state['prompts']=str(path);p.save(self.root,state)
        state=p.status(self.root)
        self.assertTrue(all(t['status']=='done' for t in state['tasks'].values() if t['kind']=='read'))
        self.assertEqual(state['tasks']['synthesize']['status'],'stale')

    def test_optimizer_binds_evaluation_to_production_build(self):
        import workflow_optimizer as opt
        candidate,run,_=self.evaluated()
        self.assertTrue(opt.compare(self.root,self.root,run,run,'development')['quality_nonregression'])
        config=read_json(run/'config.json');config['variant']='none';atomic_json(run/'config.json',config)
        with self.assertRaises(ContractError):opt.compare(self.root,self.root,run,run,'development')

    def test_worker_schema_requires_example_origin(self):
        import worker_schema as ws
        schema=ws.for_packet({'stage':'synthesize'})
        example=schema['properties']['examples']['items']
        self.assertIn('origin',example['required'])
        self.assertFalse(example['additionalProperties'])
        schema=ws.for_packet({'stage':'review','inputs':{'synthesize':{'capabilities':[{'id':'one'}],'examples':[{'id':'two'}]}}})
        self.assertEqual(set(schema['properties']['decisions']['required']),{'one','two'})


if __name__=='__main__':unittest.main()
