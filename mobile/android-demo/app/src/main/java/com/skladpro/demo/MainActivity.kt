package com.skladpro.demo

import android.annotation.SuppressLint
import android.net.ConnectivityManager
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.skladpro.demo.databinding.ActivityMainBinding

/**
 * Демо-обёртка WebView над сайтом SkladPro.
 *
 * Отвечает за требования ТЗ этапа L:
 *  - открывает сайт (URL из res/values/strings.xml -> site_url);
 *  - обрабатывает системную кнопку Back (навигация внутри WebView);
 *  - обрабатывает offline и сетевые ошибки (экран с кнопкой «Повторить»);
 *  - поддерживает загрузку файлов (аватар/фото в приложении);
 *  - pull-to-refresh.
 *
 * JavaScript и DOM storage включены НАМЕРЕННО: SPA хранит JWT в localStorage,
 * без domStorage вход не работал бы.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var lastFailed = false

    // Диалог выбора файла для <input type="file"> (загрузка фото/аватара).
    private val fileChooser =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val callback = filePathCallback ?: return@registerForActivityResult
            callback.onReceiveValue(
                WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            )
            filePathCallback = null
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        // Сбрасываем splash-тему на основную до отрисовки контента.
        setTheme(R.style.Theme_SkladPro)
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupWebView()
        setupBackHandling()

        binding.swipeRefresh.setOnRefreshListener { reload() }
        binding.retryButton.setOnClickListener { reload() }

        if (savedInstanceState == null) loadStart()
        else binding.webView.restoreState(savedInstanceState)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() = with(binding.webView.settings) {
        javaScriptEnabled = true
        domStorageEnabled = true          // localStorage для JWT
        databaseEnabled = true
        loadWithOverviewMode = true
        useWideViewPort = true
        cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
        allowFileAccess = true

        binding.webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView, request: WebResourceRequest
            ): Boolean = false  // всё грузим внутри WebView

            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                lastFailed = false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                binding.swipeRefresh.isRefreshing = false
                if (!lastFailed) showContent()
            }

            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: WebResourceError
            ) {
                // Только для основного документа, а не для под-ресурсов.
                if (request.isForMainFrame) {
                    lastFailed = true
                    showError()
                }
            }

            override fun onReceivedSslError(
                view: WebView?, handler: SslErrorHandler, error: SslError?
            ) {
                // Демо: НЕ игнорируем SSL-ошибки (безопасность). Отменяем загрузку.
                handler.cancel()
                lastFailed = true
                showError()
            }
        }

        binding.webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView?,
                callback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?
            ): Boolean {
                filePathCallback?.onReceiveValue(null)
                filePathCallback = callback
                val intent = params?.createIntent()
                if (intent == null) {
                    filePathCallback = null
                    return false
                }
                return try {
                    fileChooser.launch(intent)
                    true
                } catch (e: Exception) {
                    filePathCallback = null
                    false
                }
            }
        }
    }

    private fun setupBackHandling() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (binding.webView.canGoBack()) binding.webView.goBack()
                else finish()
            }
        })
    }

    private fun loadStart() {
        if (isOnline()) {
            binding.webView.loadUrl(getString(R.string.site_url))
        } else {
            lastFailed = true
            showError()
        }
    }

    private fun reload() {
        if (isOnline()) {
            showContent()
            binding.webView.reload()
        } else {
            binding.swipeRefresh.isRefreshing = false
            showError()
        }
    }

    private fun isOnline(): Boolean {
        val cm = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(network) ?: return false
        return caps.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    private fun showError() {
        binding.swipeRefresh.isRefreshing = false
        binding.errorView.visibility = android.view.View.VISIBLE
        binding.swipeRefresh.visibility = android.view.View.GONE
    }

    private fun showContent() {
        binding.errorView.visibility = android.view.View.GONE
        binding.swipeRefresh.visibility = android.view.View.VISIBLE
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        binding.webView.saveState(outState)
    }
}
