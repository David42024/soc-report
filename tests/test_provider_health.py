import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.config import Settings
from backend.provider_health import ProviderHealth


class ProviderHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_independent_checks_cache_and_stale_status(self):
        with (patch('backend.provider_health.groq_reply', new_callable=AsyncMock, return_value='OK') as groq,
              patch('backend.provider_health.gemini_reply', new_callable=AsyncMock,
                    side_effect=httpx.ConnectError('mensaje privado del proveedor')) as gemini):
            health = ProviderHealth(Settings(groq_api_key='synthetic-groq', gemini_api_key='synthetic-gemini',
                                             chat_gemini_model='gemini-3-flash-preview'))
            self.assertEqual(health.snapshot()['groq']['estado'], 'pendiente')
            first, second = await asyncio.gather(health.check(), health.check())
            self.assertEqual(first, second)
            self.assertEqual((first['groq']['estado'], first['gemini']['estado']), ('ok', 'error'))
            self.assertTrue(first['gemini']['vigente'])
            self.assertEqual(first['gemini']['motivo'], 'sin_respuesta')
            self.assertNotIn('mensaje privado', repr(first))
            for provider in (groq, gemini):
                provider.assert_awaited_once()
                self.assertEqual(provider.await_args.args[3][0]['content'], 'Prueba sintética de disponibilidad.')
            self.assertEqual(gemini.await_args.kwargs, {'token_limit': 384, 'thinking_level': 'low'})
            self.assertEqual(groq.await_args.kwargs, {'token_limit': 384})
            health.checked_at -= 301
            self.assertFalse(health.snapshot()['groq']['vigente'])

    async def test_unconfigured_providers_are_not_called(self):
        with patch('backend.provider_health.groq_reply', new_callable=AsyncMock) as groq:
            health = ProviderHealth(Settings())
            self.assertEqual((await health.check())['groq']['estado'], 'sin_configurar')
            groq.assert_not_awaited()

    async def test_quota_status_is_visible_without_the_response_body(self):
        request = httpx.Request('POST', 'https://provider.invalid')
        error = httpx.HTTPStatusError('privado', request=request, response=httpx.Response(429, text='privado', request=request))
        with patch('backend.provider_health.gemini_reply', new_callable=AsyncMock, side_effect=error):
            health = ProviderHealth(Settings(gemini_api_key='synthetic-key'))
            row = (await health.check())['gemini']
            self.assertEqual((row['estado'], row['motivo']), ('error', 'http_429'))
            self.assertNotIn('privado', repr(row))
