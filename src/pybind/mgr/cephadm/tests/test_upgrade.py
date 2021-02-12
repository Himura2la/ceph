import json
from unittest import mock

import pytest

from ceph.deployment.service_spec import PlacementSpec, ServiceSpec
from cephadm import CephadmOrchestrator
from cephadm.upgrade import CephadmUpgrade
from cephadm.serve import CephadmServe
from .fixtures import _run_cephadm, wait, with_host, with_service


@mock.patch("cephadm.serve.CephadmServe._run_cephadm", _run_cephadm('{}'))
def test_upgrade_start(cephadm_module: CephadmOrchestrator):
    with with_host(cephadm_module, 'test'):
        assert wait(cephadm_module, cephadm_module.upgrade_start(
            'image_id', None)) == 'Initiating upgrade to image_id'

        assert wait(cephadm_module, cephadm_module.upgrade_status()).target_image == 'image_id'

        assert wait(cephadm_module, cephadm_module.upgrade_pause()) == 'Paused upgrade to image_id'

        assert wait(cephadm_module, cephadm_module.upgrade_resume()
                    ) == 'Resumed upgrade to image_id'

        assert wait(cephadm_module, cephadm_module.upgrade_stop()) == 'Stopped upgrade to image_id'


@mock.patch("cephadm.serve.CephadmServe._run_cephadm", _run_cephadm('{}'))
@pytest.mark.parametrize("use_repo_digest",
                         [
                             False,
                             True
                         ])
def test_upgrade_run(use_repo_digest, cephadm_module: CephadmOrchestrator):
    with with_host(cephadm_module, 'host1'):
        with with_host(cephadm_module, 'host2'):
            cephadm_module.set_container_image('global', 'from_image')
            cephadm_module.use_repo_digest = use_repo_digest
            with with_service(cephadm_module, ServiceSpec('mgr', placement=PlacementSpec(host_pattern='*', count=2)), CephadmOrchestrator.apply_mgr, ''),\
                mock.patch("cephadm.module.CephadmOrchestrator.lookup_release_name",
                           return_value='foo'),\
                mock.patch("cephadm.module.CephadmOrchestrator.version",
                           new_callable=mock.PropertyMock) as version_mock,\
                mock.patch("cephadm.module.CephadmOrchestrator.get",
                           return_value={
                               # capture fields in both mon and osd maps
                               "require_osd_release": "pacific",
                               "min_mon_release": 16,
                           }):
                version_mock.return_value = 'ceph version 18.2.1 (somehash)'
                assert wait(cephadm_module, cephadm_module.upgrade_start(
                    'to_image', None)) == 'Initiating upgrade to to_image'

                assert wait(cephadm_module, cephadm_module.upgrade_status()
                            ).target_image == 'to_image'

                def _versions_mock(cmd):
                    return json.dumps({
                        'mgr': {
                            'ceph version 1.2.3 (asdf) blah': 1
                        }
                    })

                cephadm_module._mon_command_mock_versions = _versions_mock

                with mock.patch("cephadm.serve.CephadmServe._run_cephadm", _run_cephadm(json.dumps({
                    'image_id': 'image_id',
                    'repo_digests': ['to_image@repo_digest'],
                    'ceph_version': 'ceph version 18.2.3 (hash)',
                }))):

                    cephadm_module.upgrade._do_upgrade()

                assert cephadm_module.upgrade_status is not None

                with mock.patch("cephadm.serve.CephadmServe._run_cephadm", _run_cephadm(
                    json.dumps([
                        dict(
                            name=list(cephadm_module.cache.daemons['host1'].keys())[0],
                            style='cephadm',
                            fsid='fsid',
                            container_id='container_id',
                            container_image_id='image_id',
                            container_image_digests=['to_image@repo_digest'],
                            version='version',
                            state='running',
                        )
                    ])
                )):
                    CephadmServe(cephadm_module)._refresh_hosts_and_daemons()

                with mock.patch("cephadm.serve.CephadmServe._run_cephadm", _run_cephadm(json.dumps({
                    'image_id': 'image_id',
                    'repo_digests': ['to_image@repo_digest'],
                    'ceph_version': 'ceph version 18.2.3 (hash)',
                }))):
                    cephadm_module.upgrade._do_upgrade()

                _, image, _ = cephadm_module.check_mon_command({
                    'prefix': 'config get',
                    'who': 'global',
                    'key': 'container_image',
                })
                if use_repo_digest:
                    assert image == 'to_image@repo_digest'
                else:
                    assert image == 'to_image'


def test_upgrade_state_null(cephadm_module: CephadmOrchestrator):
    # This test validates https://tracker.ceph.com/issues/47580
    cephadm_module.set_store('upgrade_state', 'null')
    CephadmUpgrade(cephadm_module)
    assert CephadmUpgrade(cephadm_module).upgrade_state is None
