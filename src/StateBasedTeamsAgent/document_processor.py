"""
PDF CV Processing with Azure Document Intelligence + AI Language PII removal.

Flow:
1. User uploads PDF in Teams
2. Document Intelligence extracts text
3. AI Language removes PII (keeps name, removes phone/email/address)
4. Clean text stored in ConversationState

Uses Managed Identity (DefaultAzureCredential) - no API keys needed!
"""
import logging
from typing import Optional
import aiohttp

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.ai.textanalytics import TextAnalyticsClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


class CVDocumentProcessor:
    """Process CV PDFs: extract text and remove PII (keep name)."""
    
    def __init__(
        self,
        doc_intelligence_endpoint: str,
        language_endpoint: str,
    ):
        # Use Managed Identity - no keys needed!
        credential = DefaultAzureCredential()
        
        # Document Intelligence client for PDF extraction
        self.doc_client = DocumentIntelligenceClient(
            endpoint=doc_intelligence_endpoint,
            credential=credential
        )
        
        # Text Analytics client for PII removal
        self.text_client = TextAnalyticsClient(
            endpoint=language_endpoint,
            credential=credential
        )
        
        logger.info("[DOC PROCESSOR] Initialized with Managed Identity (no API keys)")
    
    async def process_cv_pdf(self, pdf_bytes: bytes) -> str:
        """
        Extract text from PDF CV and remove PII (keeping name).
        
        Args:
            pdf_bytes: Raw PDF file bytes
            
        Returns:
            Cleaned CV text with PII redacted (except name)
        """
        logger.info(f"[DOC PROCESSOR] Processing PDF ({len(pdf_bytes)} bytes)")
        
        # Step 1: Extract text from PDF using Document Intelligence
        extracted_text = self._extract_text_from_pdf(pdf_bytes)
        
        if not extracted_text or len(extracted_text.strip()) < 50:
            logger.warning("[DOC PROCESSOR] Very little text extracted - might be scanned/image PDF")
            return extracted_text or ""
        
        logger.info(f"[DOC PROCESSOR] Extracted {len(extracted_text)} chars from PDF")
        
        # Step 2: Remove PII (but keep person name)
        cleaned_text = self._remove_pii_keep_name(extracted_text)
        
        logger.info(f"[DOC PROCESSOR] Cleaned text: {len(cleaned_text)} chars")
        return cleaned_text
    
    def _extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF using Azure Document Intelligence."""
        try:
            # Use prebuilt-read model for general text extraction
            poller = self.doc_client.begin_analyze_document(
                "prebuilt-read",
                AnalyzeDocumentRequest(bytes_source=pdf_bytes),
            )
            result = poller.result()
            
            # Combine all extracted text
            text_parts = []
            for page in result.pages:
                for line in page.lines:
                    text_parts.append(line.content)
                text_parts.append("\n")  # Page break
            
            return "\n".join(text_parts)
            
        except Exception as e:
            logger.error(f"[DOC PROCESSOR] Document Intelligence error: {e}")
            raise
    
    def _remove_pii_keep_name(self, text: str) -> str:
        """
        Remove PII from text but keep person names.
        
        Redacts: phone, email, SSN, addresses, credit cards, etc.
        Keeps: Person names, job titles, company names, dates, locations
        """
        try:
            # PII categories to redact (NOT including Person)
            # These are direct identifiers that should be removed
            categories_to_redact = [
                "PhoneNumber",
                "Email", 
                "Address",
                "USSocialSecurityNumber",
                "CreditCardNumber",
                "IPAddress",
                "InternationalBankingAccountNumber",
                "SWIFTCode",
                "UKNationalInsuranceNumber",
                "USIndividualTaxpayerIdentification",
                "USBankAccountNumber",
            ]
            
            # Split text into chunks (API has 5120 char limit per document)
            chunks = self._split_text_into_chunks(text, max_chars=5000)
            cleaned_chunks = []
            
            for i, chunk in enumerate(chunks):
                logger.info(f"[PII] Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
                
                # Call PII detection with specific categories
                response = self.text_client.recognize_pii_entities(
                    documents=[chunk],
                    categories_filter=categories_to_redact,
                    language="en"
                )
                
                result = response[0]
                if result.is_error:
                    logger.warning(f"[PII] Error processing chunk: {result.error}")
                    cleaned_chunks.append(chunk)  # Keep original if error
                else:
                    # Use the redacted text from the API
                    cleaned_chunks.append(result.redacted_text)
                    
                    # Log what was redacted
                    if result.entities:
                        redacted_summary = [f"{e.category}" for e in result.entities]
                        logger.info(f"[PII] Redacted {len(result.entities)} items: {set(redacted_summary)}")
            
            return "\n".join(cleaned_chunks)
            
        except Exception as e:
            logger.error(f"[DOC PROCESSOR] PII removal error: {e}")
            # Return original text if PII removal fails
            return text
    
    def _split_text_into_chunks(self, text: str, max_chars: int = 5000) -> list:
        """Split text into chunks for API processing."""
        if len(text) <= max_chars:
            return [text]
        
        chunks = []
        current = ""
        
        for paragraph in text.split("\n\n"):
            if len(current) + len(paragraph) + 2 <= max_chars:
                current += paragraph + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = paragraph + "\n\n"
        
        if current:
            chunks.append(current.strip())
        
        return chunks if chunks else [text[:max_chars]]


# Singleton instance (lazy initialization)
_processor: Optional[CVDocumentProcessor] = None


def get_document_processor(config) -> CVDocumentProcessor:
    """Get or create the document processor singleton."""
    global _processor
    
    if _processor is None:
        if not config.doc_intelligence_endpoint:
            raise ValueError("Document Intelligence endpoint must be configured (DOC_INTELLIGENCE_ENDPOINT)")
        if not config.language_endpoint:
            raise ValueError("AI Language endpoint must be configured (LANGUAGE_ENDPOINT)")
            
        _processor = CVDocumentProcessor(
            doc_intelligence_endpoint=config.doc_intelligence_endpoint,
            language_endpoint=config.language_endpoint,
        )
    
    return _processor


async def download_file_from_url(url: str, auth_token: str = None) -> bytes:
    """
    Download file from URL (e.g., Teams attachment URL).
    
    Args:
        url: The URL to download from
        auth_token: Optional auth token for protected URLs
        
    Returns:
        File bytes
    """
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.read()
                logger.info(f"[DOWNLOAD] Downloaded {len(data)} bytes from URL")
                return data
            else:
                logger.error(f"[DOWNLOAD] Failed to download: HTTP {response.status}")
                raise Exception(f"Failed to download file: HTTP {response.status}")
