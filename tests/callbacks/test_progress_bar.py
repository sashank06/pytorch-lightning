import pytest

import tests.base.utils as tutils
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import ProgressBarBase, ProgressBar, ModelCheckpoint
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests.base import EvalModelTemplate


@pytest.mark.parametrize('callbacks,refresh_rate', [
    ([], 1),
    ([], 2),
    ([ProgressBar(refresh_rate=1)], 0),
    ([ProgressBar(refresh_rate=2)], 0),
    ([ProgressBar(refresh_rate=2)], 1),
])
def test_progress_bar_on(callbacks, refresh_rate):
    """Test different ways the progress bar can be turned on."""

    trainer = Trainer(
        callbacks=callbacks,
        progress_bar_refresh_rate=refresh_rate,
        max_epochs=1,
        overfit_pct=0.2,
    )

    progress_bars = [c for c in trainer.callbacks if isinstance(c, ProgressBarBase)]
    # Trainer supports only a single progress bar callback at the moment
    assert len(progress_bars) == 1
    assert progress_bars[0] is trainer.progress_bar_callback


@pytest.mark.parametrize('callbacks,refresh_rate', [
    ([], 0),
    ([], False),
    ([ModelCheckpoint('../trainer')], 0),
])
def test_progress_bar_off(callbacks, refresh_rate):
    """Test different ways the progress bar can be turned off."""

    trainer = Trainer(
        callbacks=callbacks,
        progress_bar_refresh_rate=refresh_rate,
    )

    progress_bars = [c for c in trainer.callbacks if isinstance(c, ProgressBar)]
    assert 0 == len(progress_bars)
    assert not trainer.progress_bar_callback


def test_progress_bar_misconfiguration():
    """Test that Trainer doesn't accept multiple progress bars."""
    callbacks = [ProgressBar(), ProgressBar(), ModelCheckpoint('../trainer')]
    with pytest.raises(MisconfigurationException, match=r'^You added multiple progress bar callbacks'):
        Trainer(callbacks=callbacks)


def test_progress_bar_totals():
    """Test that the progress finishes with the correct total steps processed."""

    model = EvalModelTemplate(tutils.get_default_hparams())

    trainer = Trainer(
        progress_bar_refresh_rate=1,
        val_percent_check=1.0,
        max_epochs=1,
    )
    bar = trainer.progress_bar_callback
    assert 0 == bar.total_train_batches
    assert 0 == bar.total_val_batches
    assert 0 == bar.total_test_batches

    trainer.fit(model)

    # check main progress bar total
    n = bar.total_train_batches
    m = bar.total_val_batches
    assert len(trainer.train_dataloader) == n
    assert bar.main_progress_bar.total == n + m

    # check val progress bar total
    assert sum(len(loader) for loader in trainer.val_dataloaders) == m
    assert bar.val_progress_bar.total == m

    # main progress bar should have reached the end (train batches + val batches)
    assert bar.main_progress_bar.n == n + m
    assert bar.train_batch_idx == n

    # val progress bar should have reached the end
    assert bar.val_progress_bar.n == m
    assert bar.val_batch_idx == m

    # check that the test progress bar is off
    assert 0 == bar.total_test_batches
    assert bar.test_progress_bar is None

    trainer.test(model)

    # check test progress bar total
    k = bar.total_test_batches
    assert sum(len(loader) for loader in trainer.test_dataloaders) == k
    assert bar.test_progress_bar.total == k

    # test progress bar should have reached the end
    assert bar.test_progress_bar.n == k
    assert bar.test_batch_idx == k


def test_progress_bar_fast_dev_run():
    model = EvalModelTemplate(tutils.get_default_hparams())

    trainer = Trainer(
        fast_dev_run=True,
    )

    progress_bar = trainer.progress_bar_callback
    assert 1 == progress_bar.total_train_batches
    # total val batches are known only after val dataloaders have reloaded

    trainer.fit(model)

    assert 1 == progress_bar.total_val_batches
    assert 1 == progress_bar.train_batch_idx
    assert 1 == progress_bar.val_batch_idx
    assert 0 == progress_bar.test_batch_idx

    # the main progress bar should display 2 batches (1 train, 1 val)
    assert 2 == progress_bar.main_progress_bar.total
    assert 2 == progress_bar.main_progress_bar.n

    trainer.test(model)

    # the test progress bar should display 1 batch
    assert 1 == progress_bar.test_batch_idx
    assert 1 == progress_bar.test_progress_bar.total
    assert 1 == progress_bar.test_progress_bar.n


@pytest.mark.parametrize('refresh_rate', [0, 1, 50])
def test_progress_bar_progress_refresh(refresh_rate):
    """Test that the three progress bars get correctly updated when using different refresh rates."""

    model = EvalModelTemplate(tutils.get_default_hparams())

    class CurrentProgressBar(ProgressBar):

        train_batches_seen = 0
        val_batches_seen = 0
        test_batches_seen = 0

        def on_batch_start(self, trainer, pl_module):
            super().on_batch_start(trainer, pl_module)
            assert self.train_batch_idx == trainer.batch_idx

        def on_batch_end(self, trainer, pl_module):
            super().on_batch_end(trainer, pl_module)
            assert self.train_batch_idx == trainer.batch_idx + 1
            if not self.is_disabled and self.train_batch_idx % self.refresh_rate == 0:
                assert self.main_progress_bar.n == self.train_batch_idx
            self.train_batches_seen += 1

        def on_validation_batch_end(self, trainer, pl_module):
            super().on_validation_batch_end(trainer, pl_module)
            if not self.is_disabled and self.val_batch_idx % self.refresh_rate == 0:
                assert self.val_progress_bar.n == self.val_batch_idx
            self.val_batches_seen += 1

        def on_test_batch_end(self, trainer, pl_module):
            super().on_test_batch_end(trainer, pl_module)
            if not self.is_disabled and self.test_batch_idx % self.refresh_rate == 0:
                assert self.test_progress_bar.n == self.test_batch_idx
            self.test_batches_seen += 1

    progress_bar = CurrentProgressBar(refresh_rate=refresh_rate)
    trainer = Trainer(
        callbacks=[progress_bar],
        progress_bar_refresh_rate=101,  # should not matter if custom callback provided
        train_percent_check=1.0,
        num_sanity_val_steps=2,
        max_epochs=3,
    )
    assert trainer.progress_bar_callback.refresh_rate == refresh_rate != trainer.progress_bar_refresh_rate

    trainer.fit(model)
    assert progress_bar.train_batches_seen == 3 * progress_bar.total_train_batches
    assert progress_bar.val_batches_seen == 3 * progress_bar.total_val_batches + trainer.num_sanity_val_steps

    trainer.test(model)
    assert progress_bar.test_batches_seen == progress_bar.total_test_batches
