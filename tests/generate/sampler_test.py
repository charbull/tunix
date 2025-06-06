# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Forked from flax/examples/gemma/sampler_test.py

from absl.testing import absltest
from absl.testing import parameterized
from flax import nnx
import jax
import jax.numpy as jnp
import numpy as np
from tunix.generate import sampler as sampler_lib
from tunix.tests import test_common as tc


class SamplerTest(parameterized.TestCase):

  def assertReasonableTensor(self, array, expected_shape=None):
    self.assertIsNotNone(array)
    if expected_shape is not None:
      self.assertEqual(array.shape, expected_shape)

  @parameterized.named_parameters(
      dict(
          testcase_name='case1',
          max_prompt_length=None,
          echo=False,
      ),
      dict(
          testcase_name='case2',
          max_prompt_length=4,
          echo=True,
      ),
      dict(
          testcase_name='case3',
          max_prompt_length=4,
          echo=False,
      ),
      dict(
          testcase_name='case4',
          max_prompt_length=1,
          echo=False,
      ),
  )
  def test_samples(self, max_prompt_length, echo):
    vocab = tc.MockVocab()
    transformer = tc.ToyTransformer(
        rngs=nnx.Rngs(0), vocab_size=vocab.GetPieceSize()
    )
    sampler = sampler_lib.Sampler(
        transformer=transformer,
        vocab=vocab,
        cache_config=sampler_lib.CacheConfig(
            cache_size=64,
            num_layers=4,
            num_kv_heads=4,
            head_dim=16,
        ),
    )

    result = sampler(
        ['input string', 'hello world'],
        total_generation_steps=10,
        return_logits=True,
        max_prompt_length=max_prompt_length,
        echo=echo,
    )
    self.assertIsNotNone(result)
    self.assertLen(result.logits, 2)
    if echo:
      self.assertEqual(result.logits[0].shape, (13, vocab.GetPieceSize()))
    else:
      self.assertEqual(result.logits[0].shape, (10, vocab.GetPieceSize()))

    top_p_result = sampler(
        ['input string', 'hello world'],
        total_generation_steps=10,
        temperature=9,
        top_p=0.95,
        echo=echo,
    )
    self.assertIsNotNone(top_p_result)
    self.assertNotEqual(result.text, top_p_result.text)

    top_p_result_2 = sampler(
        ['input string', 'hello world'],
        total_generation_steps=10,
        temperature=9,
        top_p=0.95,
        seed=jax.random.PRNGKey(42),
        echo=echo,
    )
    self.assertIsNotNone(top_p_result_2)
    self.assertNotEqual(top_p_result.text, top_p_result_2.text)

  def test_state_update(self):
    vocab = tc.MockVocab()
    transformer = tc.ToyTransformer(
        rngs=nnx.Rngs(0), vocab_size=vocab.GetPieceSize()
    )
    sampler = sampler_lib.Sampler(
        transformer=transformer,
        vocab=vocab,
        cache_config=sampler_lib.CacheConfig(
            cache_size=1024,
            num_layers=4,
            num_kv_heads=4,
            head_dim=16,
        ),
    )
    input_strings = ['input string', 'hello world']
    original_logits = sampler(
        input_strings, total_generation_steps=10, return_logits=True
    ).logits

    new_transformer = tc.ToyTransformer(
        rngs=nnx.Rngs(42), vocab_size=vocab.GetPieceSize()
    )
    sampler.transformer_state = nnx.variables(new_transformer, nnx.Param)
    new_logits = sampler(
        input_strings, total_generation_steps=10, return_logits=True
    ).logits
    with self.assertRaises(AssertionError):
      np.testing.assert_allclose(
          original_logits, new_logits, atol=1e-1, rtol=1e-1
      )

  def test_lora_state_update(self):
    vocab = tc.MockVocab()
    transformer = tc.get_lora_model(
        tc.ToyTransformer(rngs=nnx.Rngs(0), vocab_size=vocab.GetPieceSize())
    )

    sampler = sampler_lib.Sampler(
        transformer=transformer,
        vocab=vocab,
        cache_config=sampler_lib.CacheConfig(
            cache_size=1024,
            num_layers=4,
            num_kv_heads=4,
            head_dim=16,
        ),
    )
    input_strings = ['input string', 'hello world']
    original_logits = sampler(
        input_strings, total_generation_steps=10, return_logits=True
    ).logits

    new_transformer = tc.get_lora_model(
        tc.ToyTransformer(rngs=nnx.Rngs(42), vocab_size=vocab.GetPieceSize())
    )
    # Since LoRA_b is initialized to 0, we need to add a small perturbation to
    # the LoRA params to make sure that the new params are different from the
    # original params.
    new_lora_params = nnx.variables(new_transformer, nnx.LoRAParam)
    new_lora_params = jax.tree.map(lambda x: x + 0.1, new_lora_params)

    sampler.transformer_state = new_lora_params
    new_logits = sampler(
        input_strings, total_generation_steps=10, return_logits=True
    ).logits
    with self.assertRaises(AssertionError):
      np.testing.assert_allclose(
          original_logits, new_logits, atol=1e-1, rtol=1e-1
      )

  def test_invalid_state_update(self):
    vocab = tc.MockVocab()

    transformer = tc.ToyTransformer(
        rngs=nnx.Rngs(0), vocab_size=vocab.GetPieceSize(), num_layers=4
    )
    sampler = sampler_lib.Sampler(
        transformer=transformer,
        vocab=vocab,
        cache_config=sampler_lib.CacheConfig(
            cache_size=1024,
            num_layers=4,
            num_kv_heads=4,
            head_dim=16,
        ),
    )

    new_transformer = tc.ToyTransformer(
        rngs=nnx.Rngs(42), vocab_size=vocab.GetPieceSize(), num_layers=6
    )
    with self.assertRaisesRegex(ValueError, '.*must have the same structure.*'):
      sampler.transformer_state = nnx.variables(new_transformer, nnx.Param)

  def test_invalid_lora_state_update(self):
    vocab = tc.MockVocab()

    transformer = tc.get_lora_model(
        tc.ToyTransformer(
            rngs=nnx.Rngs(0), vocab_size=vocab.GetPieceSize(), num_layers=4
        )
    )
    sampler = sampler_lib.Sampler(
        transformer=transformer,
        vocab=vocab,
        cache_config=sampler_lib.CacheConfig(
            cache_size=1024,
            num_layers=4,
            num_kv_heads=4,
            head_dim=16,
        ),
    )

    new_transformer = tc.get_lora_model(
        tc.ToyTransformer(
            rngs=nnx.Rngs(42), vocab_size=vocab.GetPieceSize(), num_layers=6
        )
    )
    with self.assertRaisesRegex(ValueError, '.*must have the same structure.*'):
      sampler.transformer_state = nnx.variables(new_transformer, nnx.LoRAParam)

  def test_compute_attention_mask(self):
    # Check that the input mask is correctly applied when total sampling steps
    # is lower than the max cache length.
    input_mask = jnp.array([[1, 1, 0, 0, 0], [1, 1, 0, 1, 0]], dtype=jnp.bool_)
    seq_len = 8
    time_step = jnp.asarray(4, dtype=jnp.int32)
    attn_mask = sampler_lib._compute_attention_masks(
        time_step, seq_len, input_mask
    )
    expected_attn_mask = jnp.array(
        [[0, 0, 1, 1, 1, 0, 0, 0], [0, 0, 1, 0, 1, 0, 0, 0]], dtype=jnp.bool_
    )

    self.assertTrue((attn_mask.squeeze(1) == expected_attn_mask).all())

    # Check that the input mask is correctly applied when total sampling steps
    # is *longer* than the max cache length.
    seq_len = 4
    time_step = jnp.asarray(4, dtype=jnp.int32)
    attn_mask = sampler_lib._compute_attention_masks(
        time_step, seq_len, input_mask
    )
    expected_attn_mask = jnp.array(
        [[0, 1, 1, 1], [0, 1, 0, 1]], dtype=jnp.bool_
    )

    self.assertTrue((attn_mask.squeeze(1) == expected_attn_mask).all())

  def test_make_causal_attn_mask(self):
    input_mask = jnp.array([[0, 1, 1, 0], [1, 1, 1, 0]])
    attn_mask = sampler_lib.make_causal_attn_mask(input_mask, 5)
    print(attn_mask)
    expected = jnp.array([
        [
            [0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0],
            [0, 1, 1, 0, 0],
            [0, 1, 1, 0, 0],
        ],
        [
            [1, 0, 0, 0, 0],
            [1, 1, 0, 0, 0],
            [1, 1, 1, 0, 0],
            [1, 1, 1, 0, 0],
        ],
    ])
    np.testing.assert_array_equal(attn_mask, expected)


if __name__ == '__main__':
  absltest.main()
